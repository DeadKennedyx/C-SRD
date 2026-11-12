"""Versioned affine fitter supporting residue classes at declared integer widths."""
from math import gcd

from observe_runtime import locations

MOD = 2**32


def fit_rows(rows, targets, bits=32):
    if bits not in (1,8,16,32,64): raise ValueError("unsupported observation width")
    MOD=1<<bits
    if len(rows) != len(targets) or len(targets) < 3: raise ValueError("at least three paired observations required")
    if any(type(t) is not int or not 0 <= t < MOD for t in targets): raise ValueError("targets must fit the observation width")
    common = sorted(set.intersection(*(set(row) for row in rows)))
    # Minimum gcd supplies the strongest constraint on the multiplier. We check
    # all other congruences rather than assuming that this pair is sufficient.
    pairs = [(gcd((t-targets[0]) % MOD, MOD), i) for i, t in enumerate(targets[1:], 1)]
    divisor, i = min(pairs)
    # Multiplicity is meaningful for a fitted invertible map. Constant labels
    # do not identify one; do not report the unconstrained 2^32 residue count as
    # the number of odd multipliers.
    meta = {"locations_searched": len(common), "parameter_solutions": None if divisor == MOD else divisor,
            "status": "insufficient-variation" if divisor == MOD else "fitted"}
    if divisor == MOD: return [], meta
    modulus = MOD // divisor
    inverse_delta = pow(((targets[i]-targets[0]) % MOD)//divisor, -1, modulus)
    models = []
    for location in common:
        delta = (rows[i][location]-rows[0][location]) % MOD
        if delta % divisor: continue
        a = ((delta//divisor)*inverse_delta) % modulus
        if not a & 1: continue
        b = (rows[0][location]-a*targets[0]) % MOD
        if all((a*t+b) % MOD == row[location] for row, t in zip(rows, targets)):
            models.append({"location": location, "a": a, "b": b, "inverse": pow(a, -1, MOD),
                           "parameter_solutions": divisor, "multiplier_modulus": modulus,"bits":bits})
    return models, meta


def fit_affine(traces, targets):
    return fit_rows([locations(t) for t in traces], targets)


def score_models(models,traces,targets):
    rows=[locations(t) for t in traces];scored=[]
    for m in models:
        modulus=1<<m.get("bits",32)
        values=[None if m["location"] not in row else ((row[m["location"]]-m["b"])*m["inverse"])%modulus for row in rows]
        scored.append({**m,"recovered":values,"correct":sum(a==b for a,b in zip(values,targets)),
                       "available":sum(v is not None for v in values),"total":len(targets)})
    return {"models":scored,"validated_models":sum(m["correct"]==m["total"] for m in scored),
            "false_models":sum(m["available"]==m["total"] and m["correct"]!=m["total"] for m in scored),
            "inconclusive_models":sum(m["available"]!=m["total"] for m in scored)}
