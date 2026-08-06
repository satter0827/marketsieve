# Roadmap

The roadmap orders independently testable outcomes. Implemented behavior belongs in the formal
design and release history, not in this file.

## Later outcomes

### 0.9 Agent comparison and improvement foundation

- Add decision-agent contracts to the existing SDK only when working in-process and manual-file
  implementations define the same case and batch result.
- Keep the balanced implementation in an independent wheel and discover external agents through an
  entry point, while preserving agent identity and decision provenance.
- Compare in-process agents on replayable history and ChatGPT on fixed Japanese and U.S. evaluation
  sets. Store cases, requests, responses, runs, studies, and reviews separately.
- Report action-specific forward returns, sample counts, agreement, decision differences, and
  rationale differences without declaring an automatic winner or statistical advantage.
- Let improvement review read only completed studies and return observations, proposals,
  verification methods, and risks linked to case or metric IDs. It cannot modify decisions.

- Extend the Rakuten importer to non-empty holdings only after an anonymized real export defines
  its columns, account semantics, and instrument identifiers.
- Add delivery only when a working channel defines receipts, retries, idempotency, and recipient
  protection.
- Add scheduling only when one-shot commands and persisted reports have proved operationally
  reliable.
- Add news only after licensing, deduplication, reliability, and prompt-injection rules are defined.
