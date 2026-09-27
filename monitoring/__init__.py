"""Homework 7 monitoring helpers.

A frozen Homework 5 judge runs on a random sample and selected risk groups.
The random sample estimates failure prevalence. The risk groups provide more
examples for inspection. The score writer sends both results to Langfuse.

  - sample.py     random and risk sampling (hw7 hole)
  - correct.py    Rogan-Gladen correction and bootstrap interval (hw7 hole)
  - write_scores.py  repeatable score records (hw7 hole) + the Langfuse wiring
  - run_judges.py one frozen judge over the sample (instructor-provided)
  - chart.py      the prevalence-over-time chart with a threshold line
"""
