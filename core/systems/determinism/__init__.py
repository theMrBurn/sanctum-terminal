"""
determinism — Python conformance kernel for the rng + pool substrate.

Source of truth: flipper/sanctum_rpg/rng.{c,h} and pool.{c,h}.
This package must produce byte-field-identical output.
Conformance test: tests/test_conformance_rng_pool.py
Spec: sanctum-os/docs/specs/53_seed_is_truth.md §9-A
"""
