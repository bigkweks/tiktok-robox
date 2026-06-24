"""
Performance Learning System.

Closes the loop between *generating* carousels and *learning which generation
choices consistently produce the highest-quality content*. For every generated
carousel a `CarouselGenome` is recorded (its topic, hook, cover archetype, slide
count, CTA, the Content DNA that steered it, the generation settings, and its
quality + authenticity scores). From that corpus the system:

  * evaluates which hook / cover / structure / CTA patterns are selected most
    often and which survive editing with minimal changes,
  * classifies every component as strong / weak / overused / emerging,
  * ranks each component by success confidence, historical effectiveness,
    diversity and novelty,
  * and feeds a small, anti-convergence bias back into generation so the
    generator gradually prefers higher-performing structures *without* letting
    any one template dominate — preserving variation, originality, authenticity.

The whole package is a pure function of the genome corpus (JSON-backed), so it
runs and tests entirely offline.
"""
from src.learning.genome import CarouselGenome, edit_resilience_from_cycles
from src.learning.performance_store import PerformanceStore
from src.learning.recorder import build_genome

__all__ = [
    "CarouselGenome",
    "PerformanceStore",
    "build_genome",
    "edit_resilience_from_cycles",
]
