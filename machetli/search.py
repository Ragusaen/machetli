import logging
from pathlib import Path, PosixPath

from machetli.environments import LocalEnvironment, EvaluationTask
from machetli.errors import SubmissionError, PollingError
from machetli.successors import SuccessorGenerator, make_single_successor_generator, Successor
from machetli.tools import batched, configure_logging
from machetli.sas.sas_tasks import SASTask
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union


def search(initial_state: Dict[str, SASTask], successor_generator: List[SuccessorGenerator], evaluator_path: PosixPath, environment: Optional[LocalEnvironment]=None, deterministic: bool=False) -> Dict[str, SASTask]:
    """Start a Machetli search and return the resulting state.

    The search is started from the *initial state* and *successor generators*
    are then used to create transformed instances. Each instance created this
    way is evaluated with the given *evaluator* that checks if the behavior we
    are interested in is still present in the transformed instance. The search
    always commits to the transformation of the first instance where the
    evaluator succeeds (first-choice hill climbing).

    :param initial_state: is a dictionary describing the instance you want to
        simplify. The internal format of this dictionary has to match what the
        successor generators expect. Modules that include successor generators
        also provide a function to create an initial state in the correct
        format.

    :param successor_generator: is a single :class:`SuccessorGenerator
        <machetli.successors.SuccessorGenerator>` or a list of
        SuccessorGenerators. If a list [s1, ..., sn] is given, the search first
        tries all successors from s1, then from s2, and so on.

    :param evaluator_path: is the path to a Python file that is used to check if
        the behaviour that the search is analyzing is still present in the
        state. Please refer to the user documentation on :ref:`how to write an
        evaluator <usage-evaluator>`.
        
    :param environment: determines how the search should be executed. If no
        environment is specified, a :class:`LocalEnvironment
        <machetli.environments.LocalEnvironment>` is used that executes
        everything in sequence on the local machine. Alternatively, an
        implementation of :class:`SlurmEnvironment
        <machetli.environments.SlurmEnvironment>` can be used to parallelize the
        search on a cluster running the Slurm engine.

    :param deterministic:
        When evaluating successors in parallel, situations can occur that are
        impossible in a sequential environment, as results arrive not
        necessarily in the order in which the jobs are started: for example, if
        a state has successors [s1, s2, s3], a successful result for s3 could be
        available before results for s1 are available. Additionally, if the
        evaluation of s2 throws an exception, a sequential evaluation would
        never have evaluated s3. By allowing a non-deterministic successor
        choice (default) the search commits to the first successfully evaluated
        successor even if it would not have come first in a sequential order. If
        the order of the successor generators is important in your case, you can
        force a deterministic order. The search then simulates sequential
        execution.

    :return: the last state where the evaluator was successful, i.e., all
        successors of the resulting state no longer have the evaluated property.

    .. note:: 
        The initial state is never checked to have the evaluated property.
        If the result of the search is identical to the initial
        state, this can have two reasons: 

        1. The initial state is minimal with respect to the evaluated property
           and the used successor generators. In this case, you can try
           repeating the search with additional successor generators.
        2. The initial state does not have the property and neither does any of
           its successors. (If a successor has the property despite the initial
           state not having it, Machetli will nevertheless minimize the task as
           intended.) If you started from an instance that should have the
           property, this could indicate a bug in your evaluator script, which
           either doesn't reproduce the property correctly, or fails to
           recognize it.

    :Example:

    .. code-block:: python
        :linenos:
        :emphasize-lines: 4

        initial_state = sas.generate_initial_state("bugged.sas") evaluator_path
        = "./evaluator.py"

        result = search(initial_state, [sas.RemoveVariables(),
        sas.RemoveOperators()], evaluator_path)

        sas.write_file(result, "result.sas")


    """
    if environment is None:
        environment = LocalEnvironment()
    configure_logging(environment.loglevel)

    # Verify that initial state has property
    environment.start_new_iteration()
    tasks = environment.run(evaluator_path, [Successor(initial_state, "Initial state")], lambda _: None)
    for task in tasks:
        if task.status == EvaluationTask.DONE_AND_BEHAVIOR_PRESENT:
            logging.info("Initial has property.")
        elif task.status == EvaluationTask.DONE_AND_BEHAVIOR_NOT_PRESENT:
            logging.critical("Initial state does not have property!")
            raise ValueError("Initial state does not have the evaluated property.")
        elif task.status == EvaluationTask.OUT_OF_RESOURCES:
            logging.warning("Initial state evaluation ran out of resources! Cannot verify if it has the property.")
            if deterministic:
                raise ValueError("Initial state evaluation ran out of resources! Cannot verify if it has the evaluated property.")
        elif task.status == EvaluationTask.CRITICAL:
            logging.critical( "Initial state evaluation failed with a critical error! Cannot verify if it has the property.")
            if deterministic:
                raise ValueError("Initial state evaluation failed with a critical error! Cannot verify if it has the evaluated property.")
        elif task.status == EvaluationTask.CANCELED:
            logging.warning("Initial state evaluation was canceled. Cannot verify if it has the property.")
        else:
            raise ValueError(f"Unexpected task status: '{task.status}'.")

    successor_generator = make_single_successor_generator(successor_generator)

    logging.info("Starting search ...")
    current_state = initial_state
    while True:
        environment.start_new_iteration()
        successors = successor_generator.get_successors(current_state)
        try:
            improving_state, message = _get_improving_successor(
                Path(evaluator_path), successors, environment, deterministic)
        except SubmissionError as e:
            logging.critical(f"Terminating search because job submission for successor evaluation failed:\n{e}")
        except PollingError as e:
            logging.critical(f"Terminating search because querying the status of a submitted successor evaluation failed:\n{e}")

        if message:
            logging.info(message)
        if improving_state:
            current_state = improving_state
        else:
            return current_state


def _get_improving_successor(evaluator_path: PosixPath, successors: Iterator[Any], environment: LocalEnvironment, deterministic: bool) -> Union[Tuple[None, str], Tuple[Dict[str, SASTask], str]]:
    tasks_out_of_resources = set()
    for batch in batched(successors, environment.batch_size):
        task_ids = list(range(len(batch)))
        def on_task_completed(task):
            if (deterministic and task.status !=
                    EvaluationTask.DONE_AND_BEHAVIOR_NOT_PRESENT):
                # Either we have an improving successor, or there was an error.
                # In both cases deterministic mode cannot continue.
                task_ids_to_cancel = [i for i in task_ids if i > task.successor_id]
            elif (not deterministic and task.status ==
                  EvaluationTask.DONE_AND_BEHAVIOR_PRESENT):
                # We found an improving successor, so all other evaluations can
                # be canceled.
                task_ids_to_cancel = task_ids
            else:
                task_ids_to_cancel = None
            return task_ids_to_cancel

        tasks = environment.run(evaluator_path, batch, on_task_completed)
        for task in tasks:
            if task.status == EvaluationTask.DONE_AND_BEHAVIOR_NOT_PRESENT:
                continue
            elif task.status == EvaluationTask.DONE_AND_BEHAVIOR_PRESENT:
                return task.successor.state, task.successor.change_msg
            elif task.status == EvaluationTask.OUT_OF_RESOURCES:
                if deterministic:
                    return None, (task.error_msg +
                        "\nAn evaluator ran out of resources. With the option "
                        "'deterministic' an improving successor found later "
                        "would not count.")
                else:
                    tasks_out_of_resources.add(task)
            elif task.status == EvaluationTask.CRITICAL:
                if deterministic:
                    return None, (task.error_msg +
                        "\nA critical error occurred in an evaluator. With the "
                        "option 'deterministic' an improving successor found "
                        "later would not count.")
                else:
                    logging.warning(f"{task.error_msg}\nCritical error in "
                                    f"'{task.run_dir}'")
            elif task.status == EvaluationTask.CANCELED:
                # We only cancel jobs in deterministic mode if there is an earlier reason to return.
                assert not deterministic
            else:
                assert False, f"Unexpected task status: '{task.status}'."

    message = "No improving successor was found."
    if tasks_out_of_resources:
        run_dirs = [task.run_dir for task in tasks_out_of_resources]
        run_dirs_str = "\n".join(str(s) for s in sorted(run_dirs))
        message += (
            f" Note that the following tasks ran out of resources and thus"
            f" could not successfully be checked:\n{run_dirs_str}")
    return None, message
