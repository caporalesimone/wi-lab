---
description: 'Python coding conventions and guidelines'
applyTo: '**/*.py'
---

# Python Coding Conventions

## Wi-Lab Architecture

- **Layered**: API routes → managers → system commands (FastAPI → NetworkManager → commands.py).
- **Modular**: Separate packages (`wilab/api`, `wilab/wifi`, `wilab/network`) with clear interfaces.
- **File size**: Keep files <300 lines; one responsibility per class.
- **No subprocess outside `commands.py`**: All shell operations centralized in `wilab/network/commands.py`.
- **Async**: FastAPI route handlers use async/await.
- **Validation**: Use Pydantic models in `wilab/models.py` for all request/response payloads.
- **Typing**: Mandatory type hints on all function signatures and class attributes.
- **Logging**: Use standard `logging` module; no print() in production code.

## Code Style

- **PEP 8**: Follow strict adherence; 4-space indentation, max 79 chars per line.
- **Docstrings**: PEP 257 format immediately after `def`/`class` keyword.
- **Exception handling**: Catch specific exceptions, log context, return appropriate HTTP status codes.
- **Comments**: Document why, not what; complex logic should include brief explanations.
- **Type annotations**: Use `typing` module (e.g., `List[str]`, `Optional[Dict[str, int]]`).
- **Dependencies**: Document external packages and their purpose in module docstrings.

```python
def calculate_area(radius: float) -> float:
    """
    Calculate the area of a circle given the radius.
    
    Parameters:
    radius (float): The radius of the circle.
    
    Returns:
    float: The area of the circle, calculated as π * radius^2.
    """
    import math
    return math.pi * radius ** 2
```
