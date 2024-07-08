from typing import Dict, Any


class SearchResultItem:

    def __init__(self, values: Dict[str, Any]):
        self.values = values

    def __str__(self) -> str:
        return self.values.__str__()

    def path(self, path: str) -> Any:
        result = self.values
        for step in path.split('.'):
            result = result[step]
        return result

    def first_target_with_selector(self, text_type: str) -> Dict[str, Any]:
        for target in self.path('target'):
            if 'type' in target and target['type'] == text_type and 'selector' in target:
                return target

    def first_target_without_selector(self, text_type: str) -> Dict[str, Any]:
        for target in self.path('target'):
            if 'type' in target and target['type'] == text_type and 'selector' not in target:
                return target
