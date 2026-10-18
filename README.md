# AML Review Desk

[Live feedback pilot](https://aml-review-desk-himani.replit.app) · US banking research · Hybrid RAG

A research workspace for AML customer controls and laundering typologies, with cited answers, official-agency news briefs, guest-session history, and a transparent retrieval comparison.

## What is implemented

- Hybrid retrieval: routed BM25 + Nebius `Qwen/Qwen3-Embedding-8B` embeddings + Pinecone dense search, combined using reciprocal rank fusion.
- Source-grounded generation defaults to Nebius `Qwen/Qwen3-30B-A3B-Instruct-2507` after focused latency checks. Historical generation reports retain their original model/configuration labels.
- 18 captured official-source documents, 231 parent passages, and 356 semantic-search windows. The corpus includes selected FFIEC bank guidance, FinCEN advisories/rulings, Treasury risk assessment material, and FATF/Egmont indicators.
- Source citations resolve to exact stored quotes and source locators inside the app. Quotation matching is a structural check, not a semantic-entailment guarantee.
- AML news discovery from FinCEN, OCC, Federal Reserve, FDIC, NCUA, SEC and CFTC. OCC bulletins, FDIC institution letters and CFTC enforcement releases supplement general news channels.
- An executive news summary followed by What happened, Why it may matter, and additional findings from linked regulator PDFs when available. News facts and analyst interpretation remain distinct. PDF findings retain page references and explicit reading limits.
- No sign-up screen. Questions, answers, notes, reviewer assessments and up to 10 opened news briefs persist within the browser tab across refreshes. Session export preserves work outside the tab. Browser restore features may recover closed-tab sessions; this is not a secure-deletion guarantee.
- About & validation link in the footer showing measured results and generated-answer examples. User assessments cover evidence support, question coverage and applicability.

## Architecture

```text
Public source captures → original parent passages
                        → 450-word windows / 60-word overlap
                        → Nebius embeddings, 1,024 dimensions
                        → Pinecone cosine index, versioned namespace

Question → routed BM25 candidates ─┐
         → Nebius query embedding  ├→ RRF → original parent evidence
         → Pinecone candidates ───┘       → cited Nebius answer
                                          → reviewer assessment + notes
```

Dense matches resolve only to known local parent passage IDs. Remote text cannot replace the captured evidence. Source routing applies to both retrieval channels. Fused ranks are ranking signals, not confidence or legal-compliance scores. If semantic search fails, the answer explicitly identifies the degraded keyword path.

The Sources only button uses keyword retrieval without a model call. News briefs summarize the selected announcement plus up to two directly linked official regulator PDFs; news discovery is not a searchable vector news archive.

## Run locally

Python 3.10+. Install `pip install -r requirements.txt` for PDF reading and the hosted entry point. The local UI server and provider clients use the standard library. The captured policy corpus is included.

```bash
python3 configure.py
python3 configure.py --pinecone
python3 src/aml_research.py build
python3 src/hybrid_retrieval.py prepare
python3 src/hybrid_retrieval.py sync
python3 app.py
```

Open `http://127.0.0.1:8000/`. After backend changes, stop the old server with Ctrl+C and start it again, then refresh the browser.

Keys are entered through hidden terminal prompts and saved in an owner-readable `.env` ignored by Git. Never put real keys in `.env.example`, source code, screenshots, browser forms or a public ZIP. No keys are returned by the status endpoint.

Pinecone sync creates/reuses one dense serverless index (default `aml-research`, AWS `us-east-1`, cosine, 1,024 dimensions). Existing incompatible indexes are rejected; existing data is never deleted. Deterministic vector IDs and a namespace derived from the corpus, model and exact window identities make retries idempotent. All records must become visible before hybrid retrieval is activated. Prior namespaces are retained and consume storage until intentionally cleaned up.

Embeddings are cached by model, dimension and exact input text. Resuming preparation reuses cached vectors. Runtime query embeddings are cached locally by content hash; the plaintext query is not written into the embedding cache. Answer and brief caches do contain the questions and generated content and are excluded from distribution.

## Evaluation

```bash
python3 -m unittest discover -s tests -q
python3 src/evaluate_hybrid.py
python3 src/evaluate_hybrid.py --answers
```

The last command generates six illustrative answer samples (three questions × keyword/hybrid). It uses six generation calls when not cached. The internal-data question tests whether the system declines to invent an employer's SAR filing count.

### Retrieval results

All methods use the same captured corpus, source-routing policy, candidate budget (12 parent passages per channel) and evaluated top five results. RRF uses equal channel weights and constant 60. The app supplies up to eight passages to generation; the retrieval benchmark evaluates five, so those are distinct context budgets.

| Set | Method | Hit @ 5 | MRR @ 5 | nDCG @ 5 |
| --- | --- | ---: | ---: | ---: |
| Development, 24 questions | BM25 | 100.0% | 0.924 | 0.828 |
| Development, 24 questions | Dense | 95.8% | 0.917 | 0.823 |
| Development, 24 questions | Hybrid | 100.0% | 0.927 | 0.853 |
| Paraphrase challenge, 12 questions | BM25 | 25.0% | 0.188 | 0.203 |
| Paraphrase challenge, 12 questions | Dense | 91.7% | 0.787 | 0.791 |
| Paraphrase challenge, 12 questions | Hybrid | 83.3% | 0.514 | 0.574 |

Hybrid improved substantially over BM25 on the paraphrase challenge, but dense search performed better than hybrid on that set. No claim is made that hybrid always wins. The challenge median retrieval time was about 442 ms for hybrid in one sequential run with query embeddings precomputed/cached. This excludes cold embedding latency and answer generation; it is not a public-service latency SLA.

Development labels are automatically derived from known source/phrase checks. Challenge labels were manually curated by the development agent from captured passages and frozen before the comparison. They are not independently reviewed expert gold or exhaustive relevance labels. Known-passage recall is reported separately from absolute recall. One non-supporting C06 reference was removed after source inspection; the label revision and initial report are retained. No query, fusion parameter or retrieval filter was tuned on the challenge outcomes.

The six generated-answer samples, including earlier small-model outputs, remain available for claim-by-claim review. Both retrieval modes declined to invent internal SAR counts. The stronger model gave a more complete CDD explanation in the observed hybrid example. These observations are not a general answer-accuracy or faithfulness percentage. Independent AML expert adjudication is still pending.

### Evaluation artifacts

- `reports/retrieval_comparison.json` and `.csv`: per-question ranks, aggregate results, model/corpus/dataset fingerprints, protocol and timing.
- `evaluation/hybrid_challenge.json`: explicit challenge passage references.
- `evaluation/label_revision.json`: documented reference correction.
- `reports/retrieval_comparison_initial_labels.json`: preserved initial-label run.
- `reports/answer_comparison.json`: current six generated samples, with review fields pending.
- `reports/answer_comparison_small_model.json`: earlier small-model outputs, including failures.
- `reports/stronger_model_check.json`: same-context generation-model check.

The browser exposes only explicitly routed public evaluation reports. Private keys, account databases, embedding caches and runtime state remain under `.runtime` / `.env` and are not served.

## News freshness and scope

Feeds are checked on first opening the news screen in a browser load or using Refresh news. Successful per-agency listings are cached for an hour. There is no scheduled background collection or automatic overnight refresh yet. Independent source failures preserve the other feeds; stale cached listings, partial-channel failures and zero-match results are distinguished.

Discovery filters recent feed/index entries using AML terms in titles and summaries, not every article body. It does not cover every AML publication, every regulator, all historical entries, or every jurisdiction. Joint agency releases remain separate publisher entries. SEC article access can be restricted even when its feed is reachable; inaccessible bodies produce an explicit error and original-source link.

Agency-specific body extraction excludes navigation and footer content. Directly linked official regulator PDFs are read within bounded size/page limits; inaccessible, scanned and unsupported attachments are identified in document coverage. News is not itself a regulation, international indicators are not US bank requirements, and institutions must assess applicability before acting on suggestions.

## Cost and deployment boundaries

- Pinecone Database is used; Pinecone Assistant and Pinecone Inference are not required.
- Public-source embeddings and query vectors are cached; headlines require no LLM call. A fresh answer/brief uses one generation call with bounded output.
- Persistent local development guards: 100 generation attempts and 150 embedding API batches. These are request-count guards, not dollar budget guarantees. Counters include prior development use and are recorded under `.runtime`.
- The server permits three concurrent AI request slots. News and ordinary reads are not blocked behind a generation request. This is a bounded local prototype, not proof of public multi-user capacity.
- `app.py` remains loopback-only. `hosted.py` adds a separate guest-only Flask/Gunicorn feedback pilot with a fixed model, same-origin checks, request limits and a saved example. See [DEPLOYMENT.md](DEPLOYMENT.md) and `render.yaml`. Account connection, public deployment verification, durable shared counters, multi-instance coordination and load testing remain separate work. Do not expose the local development server directly to the internet.

## Source authority and reliability

The captured corpus is a research snapshot. Some documents are historical, and the source library records authority type, publication/capture dates and locators. New amendments, exceptions and relief are not comprehensively verified. A red flag is an investigative indicator, not proof of crime. The app does not certify institutional compliance or make customer-level reporting decisions.

Provider and vector clients use approved HTTPS endpoints, sanitized errors and redirect restrictions. Pinecone API implementation follows its 2025-10 vector API; generation and embedding use Nebius's OpenAI-compatible endpoints. No third-party analytics or external fonts are required by the UI.

## October 18 feedback revision

- Hosted research streams actual retrieving, drafting and checking events, with elapsed time. The target is 8 seconds on an active server, not an SLA or a cold-start ceiling. BM25 indexes are reused in memory; compact, question-specific model context reduces generation time.
- Four final live model spot checks measured 2.885–6.415 seconds server-side. This small sequential sample excludes hosting startup and browser/network overhead; it does not establish production percentiles or answer accuracy. The generated CDD sample was partial and led to the separately labelled prepared answer described below.
- A narrow CDD-program question uses a prepared source-linked explanation only when the exact two-part FFIEC passage is retrieved. It is explicitly labelled, makes no new answer-model call, and discloses the missing binding rule. This is not counted as fresh model generation.
- No direct binding CFR rule text is currently indexed. The planned eCFR gateway is not an ingested regulation. Legal-requirement questions display this gap; captured guidance must not be treated as a complete legal checklist.
- Numbered citations open the matching passage. The inspector also lists every retrieved passage, including uncited evidence. Source locators and authority categories remain visible.
- News starts with the current month and supports January–December 2026, custom dates and agency filters. A shipped archive renders immediately while a shared background refresh checks official feeds. This is an incomplete archive of captured entries, not all AML news or a complete historical backfill.
- 89 software tests pass. Five bounded adversarial probes passed, including two live indirect-injection probes with fake canaries in evidence. Direct override, credential-disclosure and explicit evasion requests are checked before provider calls. Regex/source filters are bypassable; this is not a comprehensive jailbreak or penetration assessment. Quote existence checks do not prove semantic faithfulness.

Revision evidence: `reports/revision_final_answers.json`, `reports/revision_answer_checks.json`, `reports/adversarial_checks.json`, and `reports/public_latency_before.json`. The old retrieval benchmark measures retrieval relevance only; it does not certify the revised generated answers.

## Customer-controls source update — October 18, revision 2

Added the official FinCEN consolidated CDD FAQ PDF, updated May 6, 2026, as S24. The original, SHA-256 checksum and page-preserving extract are included. This document retains individual older issue dates and selected 2026 updates; it is regulatory guidance, not binding CFR text or the relief order itself. Both retrieval channels route ordinary customer-control questions to S24, FFIEC CDD and CIP guidance. Historical S13 testimony is excluded from ordinary customer-control routing and remains available for explicit historical queries. The prepared CDD explanation cites both FinCEN and FFIEC when the relevant passages are retrieved.

Seven UI shortcuts are selected AML research topics, mixing methods, channels and underlying crimes. The coverage report names broader areas that still need dedicated source and answer validation. No new topic coverage is claimed merely because a broad national assessment mentions it.

The new corpus was embedded and synced to a separate versioned namespace in the existing Pinecone index; the prior namespace is retained. A matching packaged deployment pointer can override stale runtime state after an update. 93 software tests pass. Earlier retrieval and generated-answer benchmarks predate this corpus/routing change; they are historical results, not measured performance for this revision.
