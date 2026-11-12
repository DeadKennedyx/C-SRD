#!/usr/bin/env python3
"""Finite branch/loop executions with return and whole-memory comparisons."""
import argparse
import buffers

NAMES=('control_branch','control_early','control_loop','control_nested','control_loop_exit','control_loop_local')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--csrd',required=True);p.add_argument('--report',required=True);p.add_argument('--output-dir')
    args=p.parse_args()
    driver=buffers.harness(NAMES,unused_probe=False)
    buffers.run_fixture(args,buffers.ROOT/'tests/fixtures/memory_control.c',NAMES,driver,'guarded-memory-c11-v1',
                        len(NAMES)*len(buffers.LAYOUTS)*buffers.CASES,
                        {'pointer_offsets':buffers.LAYOUTS,'storage_words':64,'runtime_trip_counts':[0,1,2,3]})
