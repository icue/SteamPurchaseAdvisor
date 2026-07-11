# Purchase report contract

Read this file completely immediately before composing each report. Treat the English schema as semantic, not literal output: localize it, preserve section order and taxonomies, and omit unsupported optional findings.

## Contents

- Report schema
- Decision and presentation rules
- Review and fit rules
- Product-health rules
- Evidence, localization, and follow-up rules

## Report schema

```markdown
# [Localized game title](https://store.steampowered.com/app/<appid>/)

`App <appid>` [· **Early Access** only for `early-access`] · Evidence checked: YYYY-MM-DD

[SteamDB](https://steamdb.info/app/<appid>/) [· [ITAD](<itad_url>) only when supplied by the pricing script]

> [Coverage notice for either sampled review mode or another decision-relevant limitation.]

## 🎯 Decision

**Recommendation:** 🟢 Buy now / 🟡 Wait for a lower price / 🟡 Wait and reassess / 🔴 Do not buy

**Why:** [Main reason and most important condition or caveat in one sentence.]

| Signal | Assessment | Reason |
|---|---|---|
| **Game fit** | Broad / Taste-dependent / Niche / Unclear | [Supported player-fit consequence.] |
| **Product state** | Healthy / Watch / Risky / Unknown | [Current technical, content, operational-support, and—only for Early Access—development consequence.] |
| **Deal value** | Strong / Fair / Weak / Unknown | [Whether available price evidence supports the current transaction.] |

**Confidence:** High / Medium / Low — [Evidence-coverage reason.]

**Buy if:** [Concrete supported preference, tolerance, or use case.]

**Wait or skip if:** [Concrete deal-breaker, product issue, or price condition.]

## ⚠️ Before you buy

- **🎁 Active bundle available:** [First item whenever any active bundle exists: names, ITAD details links, providers, qualifying-tier prices or variable/unrecorded status, expiries, and direction to Bundle context.]
- **🎟️ Subscription access:** [Include only when `subscriptions` is a non-empty list. After the active-bundle notice when present, otherwise first: all services, known leaving dates, and an explicit US-catalog qualifier when the pricing country is not US.]
- **Epic giveaway history:** [Include only when `epic_giveaway_detected` is true. After active-bundle and subscription notices when present, otherwise before material regret risks: every returned unique exact giveaway date, or every returned unique related base-title giveaway date with SKU caveat.]
- **[Material regret risk]:** [Practical consequence and affected buyer.]
- [Up to two more material decision facts.]

## 🎮 Is this game for you?

| ✅ You'll probably enjoy it if... | ⚠️ Think twice if... |
|---|---|
| [Independent supported fit condition.] | [Independent supported rejection condition.] |

## 💬 What players actually say

### What players love

[Use either this table or bullets according to the review rules below.]

| Theme | Evidence | Player experience |
|---|---|---|
| [Theme] | Strong / Moderate / Limited | [Recurring strength and buyer consequence.] |

- **[Theme] — Strong / Moderate / Limited evidence:** [Recurring strength and buyer consequence.]

### What players criticize

[Use either this table or bullets according to the review rules below.]

| Theme | Evidence | Player experience |
|---|---|---|
| [Theme] | Strong / Moderate / Limited | [Recurring weakness and buyer consequence.] |

- **[Theme] — Strong / Moderate / Limited evidence:** [Recurring weakness and buyer consequence.]

### Even fans admit

[Weaknesses recurring in positive reviews and, when supported, why owners tolerate them.]

### Even critics concede

[Strengths recurring in negative reviews despite the negative recommendation.]

### Where players disagree

[Genuine disagreements and only evidence-supported reasons for the split.]

## 🛠️ Is the game healthy right now?

| Signal | Status | What it means |
|---|---|---|
| **Current issues** | Clear / Watch / Concerning / Unknown | [Current recurring product issues and buyer consequence.] |
| **Developer activity** | Active / Sparse / Silent / Unknown | [Early Access only; omit otherwise.] |
| **Halted-development risk** | None found / Low / Medium / High / Confirmed | [Early Access only; omit otherwise.] |

**Early Access timeline:** [Early Access only; required compact timeline or source-specific limitation.]

**What is happening now:** [Current bugs, crashes, performance, content, server or support condition; link representative claims.]

**What the developer is doing:** [Early Access only; verified activity, communication, roadmap, or gaps with exact publication dates and links.]

**What the evidence means:** [Separate official evidence, recurring owner reports, and speculation; state the purchasing consequence.]

## 💰 Is the price right?

| Price signal | Value |
|---|---|
| **Now** | ... / Unavailable |
| **Regular price** | ... / Unavailable |
| **Discount** | ... / Unavailable |
| **Steam recorded low** | ... and date / ... with date Unavailable / Unavailable |
| **Compared with recorded low** | ✅ Matches recorded low / 🔽 Establishes a new low / ⬆️ Above recorded low / Unavailable |
| **Exact-low recurrence** | Recurring / Recent isolated / Aging / Stale isolated / Stale previously repeated / Insufficient / Unavailable |
| **Recurring realistic sale level** | ... / None found / Unavailable |
| **Sustained list-price change** | ↑ Increased ... / ↓ Decreased ... / None detected / Ambiguous / Insufficient / Unavailable |
| **Epic giveaway context** | [Only when detected: every returned unique exact giveaway date, or every returned unique related base-title giveaway date with SKU caveat] |

**🎟️ Subscription access:** [Include only when `subscriptions` is a non-empty list. Use a compact sentence for one service and a compact Service/Region/Leaving table for multiple services. When the pricing country is not US, state that this is US-catalog context and does not establish local availability.]

**Bundle context:** [Omit when no active or historical records exist. Otherwise show all active and up to the three returned historical bundles; disclose truncation and partial coverage.]

| Bundle | Availability | Provider | Listed qualifying tier |
|---|---|---|---|
| [Title with required links] | Active until ... / Ended ... | ... | ... / Variable or not recorded / Not directly comparable |

**Deal value:** [Current price versus realistic recurring level and Steam low, accounting for a changed list-price regime without overriding fit or product state.]

**Buy timing:** [One transaction judgment: buy now, wait, or insufficient evidence.]

## Evidence and limitations

| Evidence | Coverage |
|---|---|
| **Review population** | ... total / Unknown |
| **Retrieval mode** | Full / Proportional recent sentiment sample / Balanced recent sentiment sample |
| **Reviews retrieved** | ... total or positive/negative corpus counts |
| **Languages observed** | ... |
| **Review limitations** | [Sampling, corpus, population comparison, or other material limitation.] |
| **Forum coverage** | [Sections and material inspected; partial failures.] |
| **Price coverage** | Steam Store-only via IsThereAnyDeal for [country] / Unavailable — [reason] |
| **Steam history** | Available — [`sale_episode_count`] / Unavailable — [reason] |
| **Epic giveaway coverage** | [Include only when a detected giveaway was reported.] |
| **Bundle coverage** | [Include only when reported, partial, or unavailable and material.] |
| **Subscription coverage** | [Include only when `subscriptions` is a non-empty list; disclose partial coverage alongside the retained records.] |

**What the gaps prevent me from concluding:** [Specific weakened or prevented conclusion, if any.]

## 🔍 Explore further

- [Dynamic compact question?]
- [Dynamic compact question?]
- [Dynamic compact question?]
```

## Decision and presentation rules

- Write a buyer's guide, not an analysis transcript. Base the recommendation on all available evidence; a historical low alone never justifies purchase.
- Keep game fit, product state, deal value, and evidence confidence distinct. Do not create numeric scores, hidden aggregation, or a second final verdict after `🎯 Decision`.
- Use tables for compact comparable facts and prose or bullets for nuance. Do not manufacture a fixed number of findings; omit weak, unsupported, redundant, or non-material content.
- Use emoji only for major navigation, recommendation reinforcement, fit orientation, and recorded-low comparison. Pair every emoji with explicit text. Never add traffic-light or decorative emoji to signal taxonomies, review evidence, ordinary findings, methodology, links, or limitations.
- Limit `⚠️ Before you buy` to three material regret risks or decision facts. Required active-bundle, subscription, and Epic giveaway notices are additional items and do not count toward that limit. Keep required notices in this order when present: active bundle, subscription, Epic giveaway, then material regret risks.
- Keep decision-relevant gaps visible in the coverage notice and Decision section. Use Evidence and limitations for audit detail, not to hide uncertainty. Lower confidence only when a missing source prevents a decision-relevant conclusion.
- Apply all price, recurrence, repricing, bundle, comparison, and timing meanings exactly as defined in `pricing-contract.md` when pricing runs.
- Treat subscription records as present only when `subscriptions` is a non-empty list. For an empty list, omit every subscription mention, including absence claims, regional caveats, the inline block, and the Subscription coverage row. Do not turn `subscription_status`, an empty lookup, or a failed lookup into buyer-facing evidence.
- With a non-empty list, show the subscription notice, inline block, and Subscription coverage row. Name every service and known leaving date; for null say no date was reported. Use “ITAD lists.” When the pricing country differs from `subscription_country`, identify the evidence as US-catalog context and state that availability in the pricing country is not established.
- State that access requires the applicable subscription and may depend on plan, platform, and account region; it did not affect the recommendation or Steam price judgment. Subscription gaps alone do not trigger the top coverage notice, lower Confidence, or alter a decision signal.
- Include Epic giveaway context in both `⚠️ Before you buy` and the price table only when `epic_giveaway_detected` is true. Deduplicate and sort every returned event date chronologically. For `epic_giveaway_scope: exact`, write: “ITAD records Epic Games Store free-giveaway date(s): [date(s)].” For `epic_giveaway_scope: related_title`, write: “ITAD records related base-title Epic Games Store free-giveaway date(s) for [title]: [date(s)]; this is not exact Steam SKU evidence.”
- Omit every Epic giveaway mention when `epic_giveaway_detected` is false or null, or when `epic_giveaway_status` is partial or unavailable. Never state or imply that the game was not given away, never predict future giveaways, and never use Epic giveaway history to alter Recommendation, Deal value, Product state, Confidence, or Buy timing.

## Review and fit rules

- Preserve four evidence groups internally: strengths and weaknesses in positive reviews, and weaknesses and strengths in negative reviews. Render them respectively as What players love, Even fans admit, What players criticize, and Even critics concede.
- Attach Strong, Moderate, or Limited evidence only when recurrence, recency, cross-language agreement, and higher-playtime observations support that qualitative evidence judgment. These labels describe evidence, not quality.
- Convert each material theme into a player or buyer consequence. Claim exact counts only when counted in retrieved material.
- Choose the format independently for What players love and What players criticize. Use a table only with at least two material themes when every theme fits one concise player-experience sentence without losing qualifications or subgroup context; otherwise use bullets for the entire subsection. Never mix both formats within one subsection.
- In Where players disagree, explain a split only from retrieved evidence, never genre assumptions.
- Treat the two fit-table columns as independent lists, not forced opposites. Leave cells blank when material finding counts differ.
- In either sampled mode, identify the exact recent sentiment-stratified design prominently and state the requested sample size, polarity quotas, and retrieved polarity counts. Calibrate confidence to consistency and coverage, never the sample positive-to-negative ratio.
- For a proportional recent sentiment sample, state that polarity quotas follow the preflight population sentiment ratio but retrieval remains recent and non-random. Report population sentiment counts or shares only from preflight totals; never extrapolate theme prevalence from sample counts. Make limited minority-polarity coverage visible when its quota is small.
- For a balanced recent sentiment sample, state that polarity quotas are deliberately balanced for strength and issue discovery. Never compare cross-polarity raw counts as population voice, rating, or prevalence.

## Product-health rules

- Classify Current issues as `clear` when adequately inspected material shows no recurring purchase-relevant issue; `watch` for limited, conditional, or actively mitigated issues; `concerning` for recurring material issues; and `unknown` for insufficient coverage.
- Describe only the inspected current state and purchasing consequence; never predict that health will persist for a specific period. Partial forum coverage supports only “no recurring issue was found in the inspected material,” not “no problem exists.”
- Use the coordinator-derived release state consistently. Never let forum activity reclassify it.
- For `early-access`, include the timeline line in every report. State the Steam-listed start, developer estimate, derived target/window/bound, and position as of evidence date when calculable. Otherwise preserve the statement or independent official target and give the precise Store Q&A or start-date limitation. Link sources when available.
- Treat timeline position as context, not a recommendation rule. Escalate it into Product state, Before you buy, halted-development risk, recommendation, or confidence only with verified progress, cadence, build condition, roadmap evidence, recurring unfinished-content reports, or another buyer-relevant factor. Extraction failure alone changes none of those judgments.
- Only for `early-access`, classify Developer activity as `active`, `sparse`, `silent`, or `unknown`, and halted-development risk as `none found`, `low`, `medium`, `high`, or `confirmed`. Separate official evidence, owner reports, and speculation.
- For `full-release`, base Product state on technical, content, server, and operational-support evidence. Sparse patches or developer posts are neutral. Report material service availability, degradation, or shutdown under Current issues, never as developer silence or halted-development risk.
- For `unknown` or `unreleased`, omit the Early Access label, timeline, Developer activity, halted-development risk, and What the developer is doing. Show the metadata gap only when it weakens a decision-relevant conclusion.

## Evidence, localization, and follow-up rules

- Place reliable Markdown links next to supported claims, prioritizing current product issues, operational support or shutdowns, and Early Access updates or roadmaps. Prefer direct topics or announcements. Never invent or reconstruct URLs.
- Enforce the exact runtime `report_language` across every buyer-facing heading, label, status, table, explanation, limitation, evidence summary, and question. Translate or paraphrase foreign evidence rather than inserting raw foreign sentences.
- Preserve official titles, company and personal names, URLs, currencies, and necessary established acronyms. Use the resolved localized title when available, otherwise the official original. Localize ordinary template and genre terms idiomatically; retain navigation emoji when renderable. Audit the report line by line.
- End with exactly three distinct, compact, action-oriented questions, one per line and no more than 12 whitespace-delimited words each; keep equivalently compact in languages without word boundaries. Derive them dynamically from findings, disagreements, uncertainty, or gaps.
- Offer only MCP-supported review, forum, event-comment, or metadata exploration. Offer development or roadmap exploration only for verified Early Access; for full releases, offer operational-support exploration only when continued service materially affects purchase. Do not repeat answered questions or offer price research, alerts, external research, benchmarks, or monitoring.
