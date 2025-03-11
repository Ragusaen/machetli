from argparse import ArgumentParser
from pathlib import Path

from machetli.sas.files import _read_task, renamed_sas

parser = ArgumentParser("Rename SAS file")
parser.add_argument("sas_file", type=Path)
parser.add_argument("-o", dest="new_sas_file", type=Path, default=None)
args = parser.parse_args()

sas_file_path: Path = args.sas_file
renamed_sas(_read_task(sas_file_path)).output((args.new_sas_file if args.new_sas_file else (sas_file_path.parent / (sas_file_path.stem + "renamed.sas"))).open("w"))



