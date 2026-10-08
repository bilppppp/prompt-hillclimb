# kvparser

A lightweight Python library for parsing, cleaning, and validating key-value headers.

## Overview

`kvparser` provides simple utilities to normalize and validate key-value formatted headers commonly used in configuration files and network protocols.

## Quick Start

```python
from kvparser import parse_headers

headers = parse_headers({
    "Content-Type": " application/json ",
    "User-Agent": "kvparser-client/1.0",
})
print(headers["Content-Type"])  # "application/json"
```

## Running Tests

```bash
pytest
```
