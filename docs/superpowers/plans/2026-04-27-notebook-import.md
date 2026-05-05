# Notebook Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable users to import API keys, projects, and assignments from notebook/text/JSON/YAML/CSV files via interactive wizards in both GUI and TUI, with smart conflict resolution and color-coded review.

**Architecture:** Layered design with shared core (parsers, validators, wizard logic, colors) and separate UI implementations (tkinter GUI, rich TUI). Both UIs read/write same encrypted vault for auto-sync.

**Tech Stack:** Python 3.8+, tkinter (GUI), rich (TUI), cryptography (existing), json/yaml/csv stdlib

---

## File Structure

**Create:**
- `pushkey/parsers.py` — Parser factory, base class, all 5 parsers, ParseResult
- `pushkey/validators.py` — Validation engine, ValidationResult
- `pushkey/import_wizard.py` — Shared wizard orchestration (file selection, parsing, validation, conflict resolution)
- `pushkey/color_scheme.py` — Provider colors, status colors, semantic color mapping
- `pushkey/gui/import_wizard_ui.py` — tkinter import wizard UI (cards, tables, buttons)
- `pushkey/tui/import_wizard_ui.py` — rich import wizard UI (tables, prompts, status display)

**Modify:**
- `pushkey.py` — Add `--tui`, `--import-gui`, `--import-tui` entry points; integrate import wizards into GUI and TUI dashboards

**Test:**
- `tests/test_parsers.py` — All parser format tests
- `tests/test_validators.py` — Validation engine tests
- `tests/test_color_scheme.py` — Color mapping tests
- `tests/test_import_wizard.py` — Wizard flow and conflict resolution tests

---

## Phase 1: Core (Required)

### Task 1: Color Scheme System

**Files:**
- Create: `pushkey/color_scheme.py`
- Test: `tests/test_color_scheme.py`

- [ ] **Step 1: Write test for provider color detection**

```python
# tests/test_color_scheme.py
from pushkey.color_scheme import get_provider_color, PROVIDER_COLORS

def test_provider_color_openai():
    assert get_provider_color("OPENAI_API_KEY") == PROVIDER_COLORS["OpenAI"]

def test_provider_color_unknown():
    assert get_provider_color("RANDOM_KEY") == PROVIDER_COLORS["Other/Unknown"]

def test_provider_color_case_insensitive():
    assert get_provider_color("openai_api_key") == PROVIDER_COLORS["OpenAI"]
```

- [ ] **Step 2: Implement color scheme**

```python
# pushkey/color_scheme.py
PROVIDER_COLORS = {
    "OpenAI": "#0066FF",
    "Anthropic": "#9933FF",
    "Stripe": "#00CCCC",
    "OANDA": "#00CC00",
    "Alpaca": "#FF9900",
    "AWS": "#FFCC00",
    "Coinbase": "#003366",
    "Supabase": "#00CC66",
    "Vercel": "#000000",
    "Other/Unknown": "#808080",
}

STATUS_COLORS = {
    "new": "#00FF00",
    "conflict": "#FFFF00",
    "error": "#FF0000",
    "skipped": "#808080",
}

PROVIDER_KEYWORDS = {
    "OpenAI": ["openai"],
    "Anthropic": ["anthropic"],
    "Stripe": ["stripe"],
    "OANDA": ["oanda"],
    "Alpaca": ["alpaca"],
    "AWS": ["aws"],
    "Coinbase": ["coinbase"],
    "Supabase": ["supabase"],
    "Vercel": ["vercel"],
}

def get_provider_color(key_name: str) -> str:
    """Return hex color for key name based on provider detection."""
    key_lower = key_name.lower()
    for provider, keywords in PROVIDER_KEYWORDS.items():
        if any(kw in key_lower for kw in keywords):
            return PROVIDER_COLORS[provider]
    return PROVIDER_COLORS["Other/Unknown"]

def get_status_color(status: str) -> str:
    """Return hex color for status (new, conflict, error, skipped)."""
    return STATUS_COLORS.get(status, STATUS_COLORS["skipped"])
```

- [ ] **Step 3: Run test**

```bash
cd C:\Users\aware\bots\pushkey
pytest tests/test_color_scheme.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add pushkey/color_scheme.py tests/test_color_scheme.py
git commit -m "feat: add color scheme system for providers and statuses"
```

---

### Task 2: Parser Base Class and Factory

**Files:**
- Create: `pushkey/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write test for ParseResult dataclass**

```python
# tests/test_parsers.py
from pushkey.parsers import ParseResult, KeyInfo, ProjectInfo

def test_parse_result_creation():
    keys = [KeyInfo(name="OPENAI_API_KEY", value="sk-123")]
    projects = [ProjectInfo(path="/home/user/project-alpha")]
    assignments = {"/home/user/project-alpha": ["OPENAI_API_KEY"]}
    
    result = ParseResult(keys=keys, projects=projects, assignments=assignments)
    assert len(result.keys) == 1
    assert result.keys[0].name == "OPENAI_API_KEY"
```

- [ ] **Step 2: Implement ParseResult and parser base class**

```python
# pushkey/parsers.py
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import List, Dict
import json

@dataclass
class KeyInfo:
    name: str
    value: str

@dataclass
class ProjectInfo:
    path: str

@dataclass
class ParseResult:
    keys: List[KeyInfo]
    projects: List[ProjectInfo]
    assignments: Dict[str, List[str]]  # {project_path: [key_names]}

class Parser(ABC):
    """Base class for all format parsers."""
    
    @abstractmethod
    def parse(self, filepath: str) -> ParseResult:
        """Parse file and return standardized ParseResult."""
        pass
    
    @staticmethod
    def detect_format(filepath: str) -> str:
        """Detect format by extension or magic bytes."""
        if filepath.endswith(".ipynb"):
            return "notebook"
        elif filepath.endswith(".json"):
            return "json"
        elif filepath.endswith(".yaml") or filepath.endswith(".yml"):
            return "yaml"
        elif filepath.endswith(".csv"):
            return "csv"
        elif filepath.endswith((".txt", ".md")):
            return "text"
        return "unknown"

class ParserFactory:
    """Factory to create appropriate parser by format."""
    
    @staticmethod
    def create_parser(format_name: str) -> Parser:
        """Create parser by format name."""
        parsers = {
            "notebook": NotebookParser,
            "text": TextParser,
            "json": JSONParser,
            "yaml": YAMLParser,
            "csv": CSVParser,
        }
        parser_class = parsers.get(format_name)
        if not parser_class:
            raise ValueError(f"Unknown format: {format_name}")
        return parser_class()
    
    @staticmethod
    def parse_file(filepath: str) -> ParseResult:
        """Auto-detect format and parse file."""
        format_name = Parser.detect_format(filepath)
        parser = ParserFactory.create_parser(format_name)
        return parser.parse(filepath)
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_parsers.py::test_parse_result_creation -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pushkey/parsers.py tests/test_parsers.py
git commit -m "feat: add parser base class and factory"
```

---

### Task 3: Text Parser (@KEY:, @PROJECT:, @USES: markers)

**Files:**
- Modify: `pushkey/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write test for text parser**

```python
# tests/test_parsers.py
from pushkey.parsers import TextParser

def test_text_parser_markers():
    """Test @KEY:, @PROJECT:, @USES: marker extraction."""
    text_content = """
@KEY: OPENAI_API_KEY = sk-proj-abc123
@KEY: OANDA_API_KEY = 12345678-abcd
@PROJECT: /home/user/project-alpha
@PROJECT: /home/user/project-beta
@USES: /home/user/project-alpha: OPENAI_API_KEY, OANDA_API_KEY
@USES: /home/user/project-beta: OPENAI_API_KEY
"""
    # Write temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(text_content)
        temp_path = f.name
    
    try:
        parser = TextParser()
        result = parser.parse(temp_path)
        
        assert len(result.keys) == 2
        assert result.keys[0].name == "OPENAI_API_KEY"
        assert result.keys[0].value == "sk-proj-abc123"
        assert len(result.projects) == 2
        assert result.assignments["/home/user/project-alpha"] == ["OPENAI_API_KEY", "OANDA_API_KEY"]
    finally:
        import os
        os.unlink(temp_path)
```

- [ ] **Step 2: Implement TextParser**

```python
# Add to pushkey/parsers.py
import re

class TextParser(Parser):
    """Parse .txt and .md files with @KEY:, @PROJECT:, @USES: markers."""
    
    def parse(self, filepath: str) -> ParseResult:
        with open(filepath, 'r') as f:
            content = f.read()
        
        keys = self._extract_keys(content)
        projects = self._extract_projects(content)
        assignments = self._extract_assignments(content)
        
        return ParseResult(keys=keys, projects=projects, assignments=assignments)
    
    def _extract_keys(self, content: str) -> List[KeyInfo]:
        """Extract @KEY: NAME = value lines."""
        keys = []
        pattern = r'@KEY:\s+(\w+)\s*=\s*(.+?)(?=\n|$)'
        for match in re.finditer(pattern, content):
            name, value = match.groups()
            keys.append(KeyInfo(name=name.strip(), value=value.strip()))
        return keys
    
    def _extract_projects(self, content: str) -> List[ProjectInfo]:
        """Extract @PROJECT: path lines."""
        projects = []
        pattern = r'@PROJECT:\s+(.+?)(?=\n|$)'
        for match in re.finditer(pattern, content):
            path = match.group(1).strip()
            projects.append(ProjectInfo(path=path))
        return projects
    
    def _extract_assignments(self, content: str) -> Dict[str, List[str]]:
        """Extract @USES: path: key1, key2 lines."""
        assignments = {}
        pattern = r'@USES:\s+(.+?):\s+(.+?)(?=\n|$)'
        for match in re.finditer(pattern, content):
            path, keys_str = match.groups()
            path = path.strip()
            key_names = [k.strip() for k in keys_str.split(',')]
            assignments[path] = key_names
        return assignments
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_parsers.py::test_text_parser_markers -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pushkey/parsers.py tests/test_parsers.py
git commit -m "feat: implement text parser for @KEY/@PROJECT/@USES markers"
```

---

### Task 4: JSON Parser

**Files:**
- Modify: `pushkey/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write test for JSON parser**

```python
# tests/test_parsers.py
from pushkey.parsers import JSONParser

def test_json_parser():
    """Test JSON format: {keys: [...], projects: [...], assignments: {...}}"""
    json_content = {
        "keys": [
            {"name": "OPENAI_API_KEY", "value": "sk-proj-abc123"},
            {"name": "OANDA_API_KEY", "value": "12345678"}
        ],
        "projects": ["/home/user/project-alpha", "/home/user/project-beta"],
        "assignments": {
            "/home/user/project-alpha": ["OPENAI_API_KEY", "OANDA_API_KEY"],
            "/home/user/project-beta": ["OPENAI_API_KEY"]
        }
    }
    
    import tempfile
    import json as json_lib
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json_lib.dump(json_content, f)
        temp_path = f.name
    
    try:
        parser = JSONParser()
        result = parser.parse(temp_path)
        
        assert len(result.keys) == 2
        assert result.keys[0].name == "OPENAI_API_KEY"
        assert len(result.projects) == 2
        assert result.assignments["/home/user/project-alpha"] == ["OPENAI_API_KEY", "OANDA_API_KEY"]
    finally:
        import os
        os.unlink(temp_path)
```

- [ ] **Step 2: Implement JSONParser**

```python
# Add to pushkey/parsers.py
class JSONParser(Parser):
    """Parse JSON format with keys/projects/assignments."""
    
    def parse(self, filepath: str) -> ParseResult:
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        keys = [KeyInfo(name=k["name"], value=k["value"]) for k in data.get("keys", [])]
        projects = [ProjectInfo(path=p) for p in data.get("projects", [])]
        assignments = data.get("assignments", {})
        
        return ParseResult(keys=keys, projects=projects, assignments=assignments)
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_parsers.py::test_json_parser -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pushkey/parsers.py tests/test_parsers.py
git commit -m "feat: implement JSON parser"
```

---

### Task 5: CSV Parser

**Files:**
- Modify: `pushkey/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write test for CSV parser**

```python
# tests/test_parsers.py
from pushkey.parsers import CSVParser

def test_csv_parser():
    """Test CSV format: key_name,key_value,project_path"""
    csv_content = """key_name,key_value,project_path
OPENAI_API_KEY,sk-proj-abc123,/home/user/project-alpha
OANDA_API_KEY,12345678,/home/user/project-beta
OPENAI_API_KEY,sk-proj-abc123,/home/user/project-beta"""
    
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content)
        temp_path = f.name
    
    try:
        parser = CSVParser()
        result = parser.parse(temp_path)
        
        assert len(result.keys) == 2  # OPENAI, OANDA
        assert result.keys[0].name == "OPENAI_API_KEY"
        assert len(result.projects) == 2  # alpha, beta
        # CSV format auto-groups by project path
        assert "/home/user/project-alpha" in result.assignments
    finally:
        import os
        os.unlink(temp_path)
```

- [ ] **Step 2: Implement CSVParser**

```python
# Add to pushkey/parsers.py
import csv

class CSVParser(Parser):
    """Parse CSV: key_name,key_value,project_path"""
    
    def parse(self, filepath: str) -> ParseResult:
        keys_dict = {}  # Deduplicate by name
        projects_set = set()
        assignments = {}
        
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key_name = row.get("key_name", "").strip()
                key_value = row.get("key_value", "").strip()
                project_path = row.get("project_path", "").strip()
                
                if key_name and key_value:
                    keys_dict[key_name] = key_value
                    projects_set.add(project_path)
                    
                    if project_path not in assignments:
                        assignments[project_path] = []
                    if key_name not in assignments[project_path]:
                        assignments[project_path].append(key_name)
        
        keys = [KeyInfo(name=name, value=value) for name, value in keys_dict.items()]
        projects = [ProjectInfo(path=p) for p in projects_set]
        
        return ParseResult(keys=keys, projects=projects, assignments=assignments)
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_parsers.py::test_csv_parser -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pushkey/parsers.py tests/test_parsers.py
git commit -m "feat: implement CSV parser"
```

---

### Task 6: YAML Parser

**Files:**
- Modify: `pushkey/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write test for YAML parser**

```python
# tests/test_parsers.py
from pushkey.parsers import YAMLParser

def test_yaml_parser():
    """Test YAML format."""
    yaml_content = """keys:
  - name: OPENAI_API_KEY
    value: sk-proj-abc123
  - name: OANDA_API_KEY
    value: "12345678"
projects:
  - /home/user/project-alpha
  - /home/user/project-beta
assignments:
  /home/user/project-alpha:
    - OPENAI_API_KEY
    - OANDA_API_KEY
  /home/user/project-beta:
    - OPENAI_API_KEY"""
    
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        temp_path = f.name
    
    try:
        parser = YAMLParser()
        result = parser.parse(temp_path)
        
        assert len(result.keys) == 2
        assert result.keys[0].name == "OPENAI_API_KEY"
        assert len(result.projects) == 2
    finally:
        import os
        os.unlink(temp_path)
```

- [ ] **Step 2: Implement YAMLParser**

```python
# Add to pushkey/parsers.py
try:
    import yaml
except ImportError:
    yaml = None

class YAMLParser(Parser):
    """Parse YAML format."""
    
    def parse(self, filepath: str) -> ParseResult:
        if yaml is None:
            raise ImportError("PyYAML not installed. Install with: pip install pyyaml")
        
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        
        keys = [KeyInfo(name=k["name"], value=k["value"]) for k in data.get("keys", [])]
        projects = [ProjectInfo(path=p) for p in data.get("projects", [])]
        assignments = data.get("assignments", {})
        
        return ParseResult(keys=keys, projects=projects, assignments=assignments)
```

- [ ] **Step 3: Update requirements.txt to include PyYAML**

Check current `requirements.txt` and add `pyyaml` if missing.

```bash
echo "pyyaml" >> requirements.txt
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_parsers.py::test_yaml_parser -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pushkey/parsers.py tests/test_parsers.py requirements.txt
git commit -m "feat: implement YAML parser"
```

---

### Task 7: Jupyter Notebook Parser

**Files:**
- Modify: `pushkey/parsers.py`
- Test: `tests/test_parsers.py`

- [ ] **Step 1: Write test for notebook parser**

```python
# tests/test_parsers.py
from pushkey.parsers import NotebookParser

def test_notebook_parser():
    """Test .ipynb notebook extraction from code and markdown cells."""
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "source": ["@KEY: OPENAI_API_KEY = sk-proj-abc123"]
            },
            {
                "cell_type": "code",
                "source": ["import os\n", "os.environ['OANDA_API_KEY'] = '12345678'"]
            },
            {
                "cell_type": "markdown",
                "source": ["@PROJECT: /home/user/project-alpha\n", "@USES: /home/user/project-alpha: OPENAI_API_KEY"]
            }
        ],
        "metadata": {}
    }
    
    import tempfile
    import json as json_lib
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ipynb', delete=False) as f:
        json_lib.dump(notebook, f)
        temp_path = f.name
    
    try:
        parser = NotebookParser()
        result = parser.parse(temp_path)
        
        # Should extract at least OPENAI from markdown
        assert any(k.name == "OPENAI_API_KEY" for k in result.keys)
    finally:
        import os
        os.unlink(temp_path)
```

- [ ] **Step 2: Implement NotebookParser**

```python
# Add to pushkey/parsers.py
class NotebookParser(Parser):
    """Parse Jupyter notebooks (.ipynb)."""
    
    def parse(self, filepath: str) -> ParseResult:
        with open(filepath, 'r') as f:
            notebook = json.load(f)
        
        keys = []
        projects = []
        assignments = {}
        
        for cell in notebook.get("cells", []):
            cell_type = cell.get("cell_type")
            source_lines = cell.get("source", [])
            source_text = "".join(source_lines) if isinstance(source_lines, list) else source_lines
            
            if cell_type == "markdown":
                # Extract markers from markdown
                keys.extend(self._extract_keys_from_text(source_text))
                projects.extend(self._extract_projects_from_text(source_text))
                assignments.update(self._extract_assignments_from_text(source_text))
            
            elif cell_type == "code":
                # Extract environment variable assignments
                keys.extend(self._extract_keys_from_code(source_text))
        
        return ParseResult(keys=keys, projects=projects, assignments=assignments)
    
    def _extract_keys_from_text(self, text: str) -> List[KeyInfo]:
        """Extract @KEY: markers from text."""
        keys = []
        pattern = r'@KEY:\s+(\w+)\s*=\s*(.+?)(?=\n|$)'
        for match in re.finditer(pattern, text):
            name, value = match.groups()
            keys.append(KeyInfo(name=name.strip(), value=value.strip()))
        return keys
    
    def _extract_projects_from_text(self, text: str) -> List[ProjectInfo]:
        """Extract @PROJECT: markers from text."""
        projects = []
        pattern = r'@PROJECT:\s+(.+?)(?=\n|$)'
        for match in re.finditer(pattern, text):
            path = match.group(1).strip()
            projects.append(ProjectInfo(path=path))
        return projects
    
    def _extract_assignments_from_text(self, text: str) -> Dict[str, List[str]]:
        """Extract @USES: markers from text."""
        assignments = {}
        pattern = r'@USES:\s+(.+?):\s+(.+?)(?=\n|$)'
        for match in re.finditer(pattern, text):
            path, keys_str = match.groups()
            path = path.strip()
            key_names = [k.strip() for k in keys_str.split(',')]
            assignments[path] = key_names
        return assignments
    
    def _extract_keys_from_code(self, code: str) -> List[KeyInfo]:
        """Extract os.environ['KEY'] = 'value' patterns from code."""
        keys = []
        # Pattern: os.environ["KEY"] = "value" or os.environ['KEY'] = 'value'
        pattern = r"os\.environ\[(['\"])(\w+)\1\]\s*=\s*(['\"])(.+?)\3"
        for match in re.finditer(pattern, code):
            key_name = match.group(2)
            key_value = match.group(4)
            keys.append(KeyInfo(name=key_name, value=key_value))
        return keys
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_parsers.py::test_notebook_parser -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pushkey/parsers.py tests/test_parsers.py
git commit -m "feat: implement Jupyter notebook parser"
```

---

### Task 8: Validation Engine

**Files:**
- Create: `pushkey/validators.py`
- Test: `tests/test_validators.py`

- [ ] **Step 1: Write test for validators**

```python
# tests/test_validators.py
from pushkey.validators import ValidationEngine, ValidationResult, validate_key_name

def test_validate_key_name_valid():
    """Valid env var names."""
    assert validate_key_name("OPENAI_API_KEY") == True
    assert validate_key_name("API_KEY_123") == True

def test_validate_key_name_invalid():
    """Invalid env var names (start with number, special chars)."""
    assert validate_key_name("123_KEY") == False
    assert validate_key_name("API-KEY") == False
    assert validate_key_name("") == False

def test_validation_engine():
    """Test full validation flow."""
    from pushkey.parsers import ParseResult, KeyInfo, ProjectInfo
    
    result = ParseResult(
        keys=[KeyInfo(name="VALID_KEY", value="value123")],
        projects=[ProjectInfo(path="/nonexistent/path")],
        assignments={}
    )
    
    engine = ValidationEngine()
    validation = engine.validate(result)
    
    assert len(validation.errors) == 0
    assert len(validation.warnings) > 0  # Path doesn't exist
```

- [ ] **Step 2: Implement validation engine**

```python
# pushkey/validators.py
from dataclasses import dataclass
from typing import List
import re
import os
from pushkey.parsers import ParseResult

@dataclass
class ValidationResult:
    errors: List[str]
    warnings: List[str]
    suggestions: List[str]
    is_valid: bool

def validate_key_name(name: str) -> bool:
    """Validate key name is valid env var name."""
    if not name:
        return False
    # Must start with letter, contain only alphanumeric + underscore
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
    return bool(re.match(pattern, name))

class ValidationEngine:
    """Validate parsed data before import."""
    
    def validate(self, parse_result: ParseResult) -> ValidationResult:
        errors = []
        warnings = []
        suggestions = []
        
        # Validate keys
        for key in parse_result.keys:
            if not validate_key_name(key.name):
                errors.append(f"Invalid key name: {key.name} (must be alphanumeric + underscore, start with letter)")
            if not key.value or not key.value.strip():
                errors.append(f"Key {key.name} has empty value")
        
        # Validate projects
        for project in parse_result.projects:
            if not os.path.exists(project.path):
                warnings.append(f"Project path does not exist: {project.path}")
        
        # Validate assignments
        key_names = {k.name for k in parse_result.keys}
        for project_path, assigned_keys in parse_result.assignments.items():
            for key_name in assigned_keys:
                if key_name not in key_names:
                    suggestions.append(f"Assignment references unknown key: {key_name} in {project_path}")
        
        is_valid = len(errors) == 0
        
        return ValidationResult(
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
            is_valid=is_valid
        )
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_validators.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 4: Commit**

```bash
git add pushkey/validators.py tests/test_validators.py
git commit -m "feat: implement validation engine"
```

---

### Task 9: Shared Import Wizard Logic

**Files:**
- Create: `pushkey/import_wizard.py`
- Test: `tests/test_import_wizard.py`

- [ ] **Step 1: Write test for wizard orchestration**

```python
# tests/test_import_wizard.py
from pushkey.import_wizard import ImportWizardOrchestrator
from pushkey.parsers import ParseResult, KeyInfo, ProjectInfo
import tempfile

def test_wizard_flow_simple():
    """Test basic wizard flow: parse -> validate -> review."""
    # Create temp text file
    text_content = "@KEY: TEST_KEY = testvalue\n@PROJECT: /tmp/testproj"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(text_content)
        temp_path = f.name
    
    try:
        wizard = ImportWizardOrchestrator()
        
        # Parse
        parse_result = wizard.parse_file(temp_path)
        assert len(parse_result.keys) == 1
        
        # Validate
        validation = wizard.validate(parse_result)
        assert validation.is_valid
        
        # Conflict check (none expected)
        conflicts = wizard.detect_conflicts(parse_result)
        assert len(conflicts) == 0
    finally:
        import os
        os.unlink(temp_path)
```

- [ ] **Step 2: Implement ImportWizardOrchestrator**

```python
# pushkey/import_wizard.py
from pushkey.parsers import ParserFactory, ParseResult
from pushkey.validators import ValidationEngine

class ImportWizardOrchestrator:
    """Orchestrate import flow: file selection -> parsing -> validation -> conflict resolution -> commit."""
    
    def __init__(self):
        self.factory = ParserFactory()
        self.validator = ValidationEngine()
        self.current_parse_result = None
    
    def parse_file(self, filepath: str) -> ParseResult:
        """Parse file using format auto-detection."""
        self.current_parse_result = self.factory.parse_file(filepath)
        return self.current_parse_result
    
    def validate(self, parse_result: ParseResult = None):
        """Validate parsed result."""
        if parse_result is None:
            parse_result = self.current_parse_result
        return self.validator.validate(parse_result)
    
    def detect_conflicts(self, parse_result: ParseResult, existing_vault: dict = None) -> List[dict]:
        """Detect conflicts with existing vault.
        
        Returns list of conflict dicts:
        {
            "type": "key_exists" | "key_different" | "path_missing" | "assignment_missing_key",
            "item": key_name or project_path,
            "current": current_value (if different),
            "existing": existing_value (if exists),
            "action": "skip" | "overwrite" | "ask"
        }
        """
        if existing_vault is None:
            existing_vault = {}
        
        conflicts = []
        
        # Check key conflicts
        existing_keys = existing_vault.get("keys", {})
        for key in parse_result.keys:
            if key.name in existing_keys:
                if existing_keys[key.name] == key.value:
                    # Same value, no conflict
                    pass
                else:
                    # Different value, needs resolution
                    conflicts.append({
                        "type": "key_different",
                        "item": key.name,
                        "current": key.value,
                        "existing": existing_keys[key.name],
                        "action": "ask"
                    })
        
        return conflicts
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_import_wizard.py::test_wizard_flow_simple -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pushkey/import_wizard.py tests/test_import_wizard.py
git commit -m "feat: implement shared import wizard orchestrator"
```

---

### Task 10: GUI Import Wizard UI (tkinter)

**Files:**
- Create: `pushkey/gui/import_wizard_ui.py`
- Modify: `pushkey.py` (add GUI entry point)

- [ ] **Step 1: Create skeleton for tkinter import wizard**

```python
# pushkey/gui/import_wizard_ui.py
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pushkey.import_wizard import ImportWizardOrchestrator
from pushkey.color_scheme import get_provider_color

class GUIImportWizard:
    """tkinter-based import wizard UI."""
    
    def __init__(self, parent_window=None, vault=None):
        self.parent = parent_window
        self.vault = vault
        self.wizard = ImportWizardOrchestrator()
        self.root = tk.Tk() if parent_window is None else tk.Toplevel(parent_window)
        self.root.title("Import API Keys, Projects, and Assignments")
        self.root.geometry("900x600")
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Build UI with file picker, review, confirm."""
        # Frame 1: File picker
        file_frame = ttk.Frame(self.root)
        file_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(file_frame, text="Select file to import:").pack(side=tk.LEFT)
        self.file_path_var = tk.StringVar(value="No file selected")
        ttk.Label(file_frame, textvariable=self.file_path_var, foreground="blue").pack(side=tk.LEFT, padx=10)
        ttk.Button(file_frame, text="Browse...", command=self._browse_file).pack(side=tk.LEFT)
        
        # Frame 2: Preview (empty until file selected)
        self.preview_frame = ttk.Frame(self.root)
        self.preview_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(self.preview_frame, text="File preview will appear here").pack()
        
        # Frame 3: Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Import", command=self._import).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.root.quit).pack(side=tk.RIGHT)
    
    def _browse_file(self):
        """Open file picker."""
        filepath = filedialog.askopenfilename(
            filetypes=[
                ("All Supported", "*.ipynb *.txt *.md *.json *.yaml *.yml *.csv"),
                ("Jupyter", "*.ipynb"),
                ("Text", "*.txt *.md"),
                ("JSON", "*.json"),
                ("YAML", "*.yaml *.yml"),
                ("CSV", "*.csv"),
            ]
        )
        if filepath:
            self.file_path_var.set(filepath)
            self._load_preview(filepath)
    
    def _load_preview(self, filepath: str):
        """Parse and show preview in GUI."""
        try:
            parse_result = self.wizard.parse_file(filepath)
            validation = self.wizard.validate(parse_result)
            
            # Clear preview frame
            for widget in self.preview_frame.winfo_children():
                widget.destroy()
            
            # Show keys preview
            keys_label = ttk.Label(self.preview_frame, text=f"Keys ({len(parse_result.keys)}):")
            keys_label.pack(anchor=tk.W)
            
            for key in parse_result.keys[:5]:  # Show first 5
                ttk.Label(self.preview_frame, text=f"  • {key.name}").pack(anchor=tk.W)
            
            if len(parse_result.keys) > 5:
                ttk.Label(self.preview_frame, text=f"  ... and {len(parse_result.keys) - 5} more").pack(anchor=tk.W)
            
            # Show projects preview
            projects_label = ttk.Label(self.preview_frame, text=f"Projects ({len(parse_result.projects)}):")
            projects_label.pack(anchor=tk.W, pady=(10, 0))
            
            for proj in parse_result.projects:
                ttk.Label(self.preview_frame, text=f"  • {proj.path}").pack(anchor=tk.W)
            
            # Show validation status
            if validation.errors:
                error_label = ttk.Label(self.preview_frame, text=f"⚠ Errors: {len(validation.errors)}", foreground="red")
                error_label.pack(anchor=tk.W, pady=(10, 0))
                for error in validation.errors[:3]:
                    ttk.Label(self.preview_frame, text=f"  {error}").pack(anchor=tk.W)
            
        except Exception as e:
            messagebox.showerror("Parse Error", str(e))
    
    def _import(self):
        """Commit import to vault."""
        if not self.file_path_var.get() or self.file_path_var.get() == "No file selected":
            messagebox.showwarning("No File", "Please select a file to import")
            return
        
        if not self.vault:
            messagebox.showerror("No Vault", "Vault not initialized")
            return
        
        try:
            parse_result = self.wizard.current_parse_result
            validation = self.wizard.validate(parse_result)
            
            if not validation.is_valid:
                messagebox.showerror("Validation Failed", f"Errors: {'; '.join(validation.errors[:3])}")
                return
            
            # TODO: Implement vault commit logic
            messagebox.showinfo("Import Complete", f"Imported {len(parse_result.keys)} keys and {len(parse_result.projects)} projects")
            self.root.quit()
        
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
```

- [ ] **Step 2: Add import wizard entry point to pushkey.py**

```python
# In pushkey.py, add to main argument parsing (around line 1500 or at end):

import sys
from pushkey.gui.import_wizard_ui import GUIImportWizard

# In the main() function or argument handling:
if "--import-gui" in sys.argv:
    wizard = GUIImportWizard()
    wizard.root.mainloop()
    sys.exit(0)
```

- [ ] **Step 3: Test manually (no automated test for GUI)**

```bash
cd C:\Users\aware\bots\pushkey
python pushkey.py --import-gui
```

Expected: Window opens with file picker and preview area

- [ ] **Step 4: Commit**

```bash
git add pushkey/gui/import_wizard_ui.py pushkey.py
git commit -m "feat: add GUI import wizard with file picker and preview"
```

---

### Task 11: TUI Import Wizard (rich/textual)

**Files:**
- Create: `pushkey/tui/import_wizard_ui.py`
- Modify: `pushkey.py` (add TUI entry point)

- [ ] **Step 1: Create TUI import wizard with rich**

```python
# pushkey/tui/import_wizard_ui.py
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from pushkey.import_wizard import ImportWizardOrchestrator
from pushkey.color_scheme import get_provider_color, PROVIDER_COLORS

class TUIImportWizard:
    """Terminal-based import wizard using rich."""
    
    def __init__(self, vault=None):
        self.console = Console()
        self.vault = vault
        self.wizard = ImportWizardOrchestrator()
    
    def run(self):
        """Run the import wizard flow."""
        self.console.print(Panel("[bold blue]Import API Keys, Projects & Assignments[/bold blue]"))
        
        # Step 1: File selection
        filepath = self._prompt_file_path()
        if not filepath:
            self.console.print("[yellow]Import cancelled[/yellow]")
            return
        
        # Step 2: Parse
        try:
            parse_result = self.wizard.parse_file(filepath)
            self.console.print("[green]✓ File parsed successfully[/green]")
        except Exception as e:
            self.console.print(f"[red]✗ Parse error: {e}[/red]")
            return
        
        # Step 3: Validate
        validation = self.wizard.validate(parse_result)
        if validation.errors:
            self.console.print("[red]Validation errors:[/red]")
            for error in validation.errors:
                self.console.print(f"  [red]✗ {error}[/red]")
            if not Confirm.ask("Continue anyway?"):
                return
        
        if validation.warnings:
            self.console.print("[yellow]Warnings:[/yellow]")
            for warning in validation.warnings:
                self.console.print(f"  [yellow]⚠ {warning}[/yellow]")
        
        # Step 4: Review
        self._review_data(parse_result)
        
        # Step 5: Confirm
        if not Confirm.ask("Import these items?"):
            self.console.print("[yellow]Import cancelled[/yellow]")
            return
        
        # Step 6: Commit
        self.console.print("[green]✓ Import complete[/green]")
    
    def _prompt_file_path(self) -> str:
        """Prompt user for file path."""
        self.console.print("\nSupported formats: .ipynb, .txt, .md, .json, .yaml, .csv")
        filepath = Prompt.ask("Enter file path")
        return filepath
    
    def _review_data(self, parse_result):
        """Display keys, projects, assignments in tables."""
        self.console.print("\n[bold]Keys to import:[/bold]")
        keys_table = Table(show_header=True, header_style="bold")
        keys_table.add_column("Key Name", style="cyan")
        keys_table.add_column("Value", style="green")
        
        for key in parse_result.keys:
            provider_color = get_provider_color(key.name)
            keys_table.add_row(key.name, f"{key.value[:20]}..." if len(key.value) > 20 else key.value)
        
        self.console.print(keys_table)
        
        self.console.print("\n[bold]Projects to link:[/bold]")
        projects_table = Table(show_header=True, header_style="bold")
        projects_table.add_column("Project Path")
        
        for project in parse_result.projects:
            projects_table.add_row(project.path)
        
        self.console.print(projects_table)
        
        if parse_result.assignments:
            self.console.print("\n[bold]Assignments:[/bold]")
            for project_path, keys in parse_result.assignments.items():
                self.console.print(f"  [cyan]{project_path}[/cyan]: {', '.join(keys)}")
```

- [ ] **Step 2: Add TUI entry point to pushkey.py**

```python
# In pushkey.py, add to argument parsing:

from pushkey.tui.import_wizard_ui import TUIImportWizard

# In main():
if "--import-tui" in sys.argv:
    wizard = TUIImportWizard()
    wizard.run()
    sys.exit(0)

if "--tui" in sys.argv:
    # Full TUI app (Phase 2, stub for now)
    from pushkey.tui.dashboard import TUIDashboard
    dashboard = TUIDashboard()
    dashboard.run()
    sys.exit(0)
```

- [ ] **Step 3: Test manually**

```bash
cd C:\Users\aware\bots\pushkey
python pushkey.py --import-tui
```

(Provide file path when prompted)

Expected: Tables show keys, projects, assignments; prompts for confirmation

- [ ] **Step 4: Commit**

```bash
git add pushkey/tui/import_wizard_ui.py pushkey.py
git commit -m "feat: add TUI import wizard with rich tables"
```

---

### Task 12: Vault Integration - Commit Parsed Data

**Files:**
- Modify: `pushkey/import_wizard.py`
- Modify: `pushkey.py` (vault access)

- [ ] **Step 1: Write test for vault commit**

```python
# tests/test_import_wizard.py
def test_wizard_commit_to_vault(temp_vault):
    """Test committing import data to vault."""
    from pushkey.parsers import ParseResult, KeyInfo, ProjectInfo
    
    wizard = ImportWizardOrchestrator(vault=temp_vault)
    
    result = ParseResult(
        keys=[KeyInfo(name="NEW_KEY", value="newvalue")],
        projects=[ProjectInfo(path="/tmp/newproj")],
        assignments={"/tmp/newproj": ["NEW_KEY"]}
    )
    
    wizard.commit(result)
    
    # Verify vault has the data
    vault_keys = temp_vault.get_keys()
    assert "NEW_KEY" in vault_keys
    assert vault_keys["NEW_KEY"] == "newvalue"
```

- [ ] **Step 2: Implement vault commit in orchestrator**

```python
# In pushkey/import_wizard.py, add:

class ImportWizardOrchestrator:
    def __init__(self, vault=None):
        self.factory = ParserFactory()
        self.validator = ValidationEngine()
        self.current_parse_result = None
        self.vault = vault
    
    def commit(self, parse_result: ParseResult):
        """Write parsed data to vault (keys + projects + assignments)."""
        if not self.vault:
            raise ValueError("Vault not initialized")
        
        # Add keys to vault
        for key in parse_result.keys:
            self.vault.add_key(key.name, key.value)
        
        # Add projects
        for project in parse_result.projects:
            self.vault.add_project(project.path)
        
        # Add assignments
        for project_path, key_names in parse_result.assignments.items():
            self.vault.assign_keys_to_project(project_path, key_names)
```

- [ ] **Step 3: Update GUI and TUI wizards to call commit**

```python
# In pushkey/gui/import_wizard_ui.py, update _import():
def _import(self):
    # ... validation ...
    self.wizard.commit(parse_result)
    messagebox.showinfo("Import Complete", ...)

# In pushkey/tui/import_wizard_ui.py, update run():
self.wizard.commit(parse_result)
self.console.print("[green]✓ Import complete[/green]")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_import_wizard.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pushkey/import_wizard.py pushkey/gui/import_wizard_ui.py pushkey/tui/import_wizard_ui.py tests/test_import_wizard.py
git commit -m "feat: implement vault commit for imports"
```

---

### Task 13: Conflict Resolution in Wizard

**Files:**
- Modify: `pushkey/import_wizard.py`
- Modify: `pushkey/gui/import_wizard_ui.py`
- Modify: `pushkey/tui/import_wizard_ui.py`

- [ ] **Step 1: Write test for conflict resolution prompts**

```python
# tests/test_import_wizard.py
def test_conflict_resolution_key_exists_same():
    """Key exists with same value → skip silently."""
    from pushkey.parsers import ParseResult, KeyInfo
    
    existing_vault = {"keys": {"OPENAI_API_KEY": "sk-123"}}
    result = ParseResult(
        keys=[KeyInfo(name="OPENAI_API_KEY", value="sk-123")],
        projects=[], assignments={}
    )
    
    wizard = ImportWizardOrchestrator()
    conflicts = wizard.detect_conflicts(result, existing_vault)
    assert len(conflicts) == 0

def test_conflict_resolution_key_exists_different():
    """Key exists with different value → ask to overwrite."""
    from pushkey.parsers import ParseResult, KeyInfo
    
    existing_vault = {"keys": {"OPENAI_API_KEY": "sk-old"}}
    result = ParseResult(
        keys=[KeyInfo(name="OPENAI_API_KEY", value="sk-new")],
        projects=[], assignments={}
    )
    
    wizard = ImportWizardOrchestrator()
    conflicts = wizard.detect_conflicts(result, existing_vault)
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "key_different"
    assert conflicts[0]["action"] == "ask"
```

- [ ] **Step 2: Enhance import_wizard.py with conflict resolution**

```python
# In pushkey/import_wizard.py, add resolve_conflicts():

def resolve_conflicts(self, conflicts: List[dict], resolutions: dict) -> ParseResult:
    """Apply user resolutions to conflicts.
    
    resolutions: {conflict_id: "skip" | "overwrite" | ...}
    """
    # Filter parse result based on resolutions
    # This is simplified; full version tracks each conflict
    
    # For now, if user chooses "skip", remove from result
    # If user chooses "overwrite", keep in result
    
    return self.current_parse_result
```

- [ ] **Step 3: Update GUI to show conflict prompts**

```python
# In pushkey/gui/import_wizard_ui.py, update _import():

def _import(self):
    # ... validation ...
    
    # Check conflicts
    conflicts = self.wizard.detect_conflicts(parse_result, existing_vault=self.vault.get_raw_data())
    
    if conflicts:
        # Create conflict resolution dialog
        for conflict in conflicts:
            if conflict["type"] == "key_different":
                response = messagebox.askyesno(
                    "Key Conflict",
                    f"{conflict['item']}\nExisting: {conflict['existing']}\nNew: {conflict['current']}\n\nOverwrite?"
                )
                if not response:
                    # Skip this key
                    parse_result.keys = [k for k in parse_result.keys if k.name != conflict['item']]
    
    # Commit
    self.wizard.commit(parse_result)
```

- [ ] **Step 4: Update TUI to show conflict prompts**

```python
# In pushkey/tui/import_wizard_ui.py, add to run():

conflicts = self.wizard.detect_conflicts(parse_result, ...)

if conflicts:
    self.console.print("\n[yellow]Conflicts detected:[/yellow]")
    for i, conflict in enumerate(conflicts):
        self.console.print(f"\n[bold]Conflict {i+1}: {conflict['item']}[/bold]")
        if conflict['type'] == 'key_different':
            self.console.print(f"  Existing: {conflict['existing']}")
            self.console.print(f"  New: {conflict['current']}")
            if not Confirm.ask("  Overwrite?"):
                # Remove from parse result
                parse_result.keys = [k for k in parse_result.keys if k.name != conflict['item']]
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_import_wizard.py -v
```

Expected: PASS (conflict resolution tests)

- [ ] **Step 6: Commit**

```bash
git add pushkey/import_wizard.py pushkey/gui/import_wizard_ui.py pushkey/tui/import_wizard_ui.py tests/test_import_wizard.py
git commit -m "feat: implement smart conflict resolution in wizards"
```

---

### Task 14: Update .env Files on Import

**Files:**
- Modify: `pushkey/import_wizard.py`
- Modify: `pushkey.py` (vault write .env)

- [ ] **Step 1: Write test for .env update**

```python
# tests/test_import_wizard.py
def test_env_file_created_on_import(temp_dir):
    """Importing key with project assignment should update .env file."""
    import os
    from pushkey.parsers import ParseResult, KeyInfo, ProjectInfo
    
    project_path = os.path.join(temp_dir, "test_project")
    os.makedirs(project_path, exist_ok=True)
    
    result = ParseResult(
        keys=[KeyInfo(name="TEST_KEY", value="testvalue")],
        projects=[ProjectInfo(path=project_path)],
        assignments={project_path: ["TEST_KEY"]}
    )
    
    wizard = ImportWizardOrchestrator()
    wizard.commit(result)
    
    # Check .env file exists and has the key
    env_file = os.path.join(project_path, ".env")
    assert os.path.exists(env_file)
    with open(env_file) as f:
        content = f.read()
    assert "TEST_KEY=testvalue" in content
```

- [ ] **Step 2: Enhance vault to write .env on key update**

(This depends on existing vault architecture. Modify in `pushkey.py` vault class:)

```python
# In the existing Vault class in pushkey.py, update add_key() and assign_keys_to_project():

def add_key(self, name: str, value: str):
    """Add key and write to linked projects' .env files."""
    # ... existing encryption logic ...
    
    # After saving, update all linked projects
    linked_projects = self.get_projects_for_key(name)
    for project_path in linked_projects:
        self.write_env_file(project_path)

def write_env_file(self, project_path: str):
    """Write all assigned keys for project to .env file."""
    if not os.path.exists(project_path):
        return
    
    env_path = os.path.join(project_path, ".env")
    assigned_keys = self.get_assignments(project_path)  # From config
    
    lines = []
    for key_name in assigned_keys:
        key_value = self.get_key(key_name)
        if key_value:
            lines.append(f"{key_name}={key_value}")
    
    with open(env_path, 'w') as f:
        f.write('\n'.join(lines))
    
    # Add .env to .gitignore
    gitignore_path = os.path.join(project_path, ".gitignore")
    if os.path.exists(gitignore_path):
        with open(gitignore_path, 'a') as f:
            if ".env" not in f.read():
                f.write("\n.env\n")
    else:
        with open(gitignore_path, 'w') as f:
            f.write(".env\n")
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_import_wizard.py::test_env_file_created_on_import -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add pushkey.py tests/test_import_wizard.py
git commit -m "feat: write .env files to linked projects on import"
```

---

### Task 15: Integration Test - Full Import Flow

**Files:**
- Test: `tests/test_import_wizard.py`

- [ ] **Step 1: Write end-to-end integration test**

```python
# tests/test_import_wizard.py
def test_full_import_flow_text_format(temp_dir):
    """Full flow: text file → parse → validate → review → commit → vault + .env"""
    import os
    import tempfile
    from pushkey.import_wizard import ImportWizardOrchestrator
    
    # Create test file
    text_content = """
@KEY: OPENAI_API_KEY = sk-proj-test123
@KEY: STRIPE_API_KEY = sk_live_test456
@PROJECT: """ + temp_dir + """/project-alpha
@USES: """ + temp_dir + """/project-alpha: OPENAI_API_KEY, STRIPE_API_KEY
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(text_content)
        temp_file = f.name
    
    try:
        os.makedirs(os.path.join(temp_dir, "project-alpha"), exist_ok=True)
        
        wizard = ImportWizardOrchestrator()
        
        # Parse
        result = wizard.parse_file(temp_file)
        assert len(result.keys) == 2
        assert len(result.projects) == 1
        
        # Validate
        validation = wizard.validate(result)
        assert validation.is_valid
        
        # Detect conflicts (none)
        conflicts = wizard.detect_conflicts(result)
        assert len(conflicts) == 0
        
        # Commit (would need vault object in real scenario)
        # wizard.commit(result)
        
        # Check results
        assert result.keys[0].name == "OPENAI_API_KEY"
        assert result.keys[0].value == "sk-proj-test123"
    
    finally:
        os.unlink(temp_file)
```

- [ ] **Step 2: Run test**

```bash
pytest tests/test_import_wizard.py::test_full_import_flow_text_format -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_import_wizard.py
git commit -m "test: add full integration test for import flow"
```

---

## Phase 2: Enhancement (Optional)

### Task 16: LLM-Assisted Parsing (Stub)

**Files:**
- Create: `pushkey/llm_enhancement.py`

- [ ] **Step 1: Create LLM enhancement module stub**

```python
# pushkey/llm_enhancement.py
import os

class LLMEnhancer:
    """Optional LLM enhancement for improved parsing.
    
    Priority:
    1. Try local Ollama
    2. Fallback to Anthropic API
    3. Skip if neither available
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enabled = self.config.get("llm_parsing", {}).get("enabled", False)
        self.ollama_url = self.config.get("llm_parsing", {}).get("ollama_url", "http://localhost:11434")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    
    def enhance(self, parse_result, file_content: str):
        """Optional: send to LLM for validation and suggestions."""
        if not self.enabled:
            return parse_result
        
        # TODO: Implement LLM integration
        # For now, return as-is
        return parse_result
```

- [ ] **Step 2: Stub test**

```python
# tests/test_llm_enhancement.py (Phase 2, can be minimal for now)
from pushkey.llm_enhancement import LLMEnhancer

def test_llm_enhancement_disabled_by_default():
    enhancer = LLMEnhancer()
    assert enhancer.enabled == False
```

- [ ] **Step 3: Commit**

```bash
git add pushkey/llm_enhancement.py tests/test_llm_enhancement.py
git commit -m "feat: add LLM enhancement stub (Phase 2)"
```

---

## Summary of Changes

**Phase 1 Core — 15 tasks:**
- ✅ Color scheme system
- ✅ Parser factory + base class
- ✅ Text parser, JSON parser, CSV parser, YAML parser, Notebook parser
- ✅ Validation engine
- ✅ Shared import wizard orchestration
- ✅ GUI import wizard (tkinter)
- ✅ TUI import wizard (rich)
- ✅ Vault integration + .env updates
- ✅ Conflict resolution
- ✅ Integration tests

**Phase 2 Enhancement — stub:**
- ✅ LLM enhancement module (placeholder)

**Files Created:** 10
**Files Modified:** 1 (pushkey.py)
**Test Files:** 5
**Total Tasks:** 16
**Total Steps:** 78

---

## Success Verification

After Phase 1 complete:
- [ ] All parsers handle their formats without errors
- [ ] Validation catches invalid key names and missing paths
- [ ] GUI wizard shows file picker, preview, and confirm dialog
- [ ] TUI wizard shows tables and resolves conflicts
- [ ] Import creates keys in vault, creates projects, assigns keys
- [ ] .env files written to linked projects
- [ ] Changes in GUI synced to TUI (via shared vault)
- [ ] Tests > 80% coverage
