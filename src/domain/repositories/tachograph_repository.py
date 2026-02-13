from abc import ABC, abstractmethod
from src.domain.models.entities import TachographFile

class TachographRepository(ABC):
    @abstractmethod
    def get_by_path(self, path: str) -> TachographFile:
        """
        Parses a tachograph file from the given path and returns a domain entity.
        
        Args:
            path: The file path to the .ddd file.
            
        Returns:
            TachographFile: The parsed domain entity.
        """
        pass
