from __future__ import annotations

import logging
from typing import Literal

import ase
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.stress import full_3x3_to_voigt_6_stress
from torch.utils.data import Dataset
from tqdm import tqdm
from typing_extensions import override

from ..registry import data_registry
from ..util import optional_import_error_message
from .base import DatasetConfigBase

log = logging.getLogger(__name__)


@data_registry.register
class MPTrajDatasetConfig(DatasetConfigBase):
    """Configuration for a dataset stored in the Materials Project database."""

    type: Literal["mptraj"] = "mptraj"
    """Discriminator for the MPTraj dataset."""

    split: Literal["train", "val", "test"] = "train"
    """Split of the dataset to use."""

    min_num_atoms: int | None = 5
    """Minimum number of atoms to be considered. Drops structures with fewer atoms."""

    max_num_atoms: int | None = None
    """Maximum number of atoms to be considered. Drops structures with more atoms."""

    elements: list[str] | None = None
    """
    List of elements to be considered. Drops structures with elements not in the list.
    Subsets are also allowed. For example, ["Li", "Na"] will keep structures with either Li or Na.
    """

    @override
    def create_dataset(self):
        return MPTrajDataset(self)


class MPTrajDataset(Dataset[ase.Atoms]):
    def __init__(self, config: MPTrajDatasetConfig):
        super().__init__()

        with optional_import_error_message("datasets"):
            import datasets  # type: ignore[reportMissingImports] # noqa

        self.config = config

        dataset = datasets.load_dataset("nimashoghi/mptrj", split=self.config.split)
        assert isinstance(dataset, datasets.Dataset)
        dataset.set_format("numpy")
        self.atoms_list = []
        pbar = tqdm(dataset, desc="Loading dataset...")
        for entry in dataset:
            atoms = self._load_atoms_from_entry(dict(entry))
            if self._filter_atoms(atoms):
                self.atoms_list.append(atoms)
            pbar.update(1)
        pbar.close()

    def _load_atoms_from_entry(self, entry: dict) -> Atoms:
        atoms = Atoms(
            positions=entry["positions"],
            numbers=entry["numbers"],
            cell=entry["cell"],
            pbc=True,
        )
        labels = {
            "energy": entry["corrected_total_energy"].item(),
            "forces": entry["forces"],
            "stress": full_3x3_to_voigt_6_stress(entry["stress"]),
        }
        calc = SinglePointCalculator(atoms, **labels)
        atoms.calc = calc
        return atoms

    def _filter_atoms(self, atoms: Atoms) -> bool:
        if (
            self.config.min_num_atoms is not None
            and len(atoms) < self.config.min_num_atoms
        ):
            return False
        if (
            self.config.max_num_atoms is not None
            and len(atoms) > self.config.max_num_atoms
        ):
            return False
        if self.config.elements is not None:
            elements = set(atoms.get_chemical_symbols())
            if not set(self.config.elements) >= elements:
                return False
        return True

    @override
    def __getitem__(self, idx: int) -> Atoms:
        return self.atoms_list[idx]

    def __len__(self):
        return len(self.atoms_list)
