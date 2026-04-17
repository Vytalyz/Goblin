# Time Session Contract

The canonical time/session contract must define:

- broker timezone and offset policy
- comparison time basis
- London/New York overlap definitions
- DST transition handling
- holiday policy
- market-open and market-close normalization

## Validation Use

- All cross-channel comparisons must declare the same time basis before they can be trusted.
- Truth-alignment reports must surface any channel whose declared timezone basis differs from the comparison basis.
- Session drift is an incident trigger when it affects executable parity or live reconciliation.
