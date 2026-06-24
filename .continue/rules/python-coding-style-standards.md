---
globs: "['backend/**/*.py']"
description: Mandates idiomatic Python practices, strong typing, clear naming,
  and professional error management in backend code.
alwaysApply: true
---

All backend code must be highly Pythonic, using explicit type hinting (PEP 484). Variable and function names must be descriptive, avoiding abbreviations. Utilize structured error handling (`try...except`) to map domain exceptions to appropriate HTTP responses for the API layer.