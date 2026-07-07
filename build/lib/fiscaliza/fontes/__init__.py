"""Conectores para as bases de dados públicas fiscalizáveis."""

from .transparencia import PortalTransparencia
from .tse import TSE
from .receita import ReceitaCNPJ
from .bcb import BancoCentral
from .ibge import IBGE

__all__ = ["PortalTransparencia", "TSE", "ReceitaCNPJ", "BancoCentral", "IBGE"]
