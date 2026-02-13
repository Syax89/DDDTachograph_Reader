from src.domain.repositories.tachograph_repository import TachographRepository
from src.domain.models.entities import TachographFile
from src.infrastructure.mappers.tacho_mapper import TachoDomainMapper
from ddd_parser import TachoParser
import os

class FileTachoRepository(TachographRepository):
    def get_by_path(self, path: str) -> TachographFile:
        """
        Parses a tachograph file from the given path and returns a domain entity.
        
        Args:
            path: The file path to the .ddd file.
            
        Returns:
            TachographFile: The parsed domain entity.
            
        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If parsing fails.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
            
        parser = TachoParser(path)
        result = parser.parse()
        
        # Check integrity or errors in metadata if needed
        # But the mapper handles N/A values gracefully.
        
        return TachoDomainMapper.to_domain(result)
