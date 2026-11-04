# Tec Tha — Team, roles and responsibilities

The team you would hire to build, sell and run Tec Tha Vital. Each role is also a Claude agent (`.claude/agents/<role>.md`) that reads [PRODUCT_KNOWLEDGE.md](PRODUCT_KNOWLEDGE.md) first.

When funds allow, hire in this order: **Implementation Manager**, then **Full-stack Engineer**, then **Healthcare Domain Lead (part-time advisor)**. Until then, the founder plus these agents cover every role.

| # | Role | Experience to hire | Owns | Main deliverables |
|---|---|---|---|---|
| 1 | Head of Product | 12+ yrs SaaS product, 5+ in healthcare IT | What we build and why; scope; priorities | PRD, roadmap, acceptance criteria, release notes |
| 2 | Healthcare Domain & Compliance Lead | 15+ yrs hospital operations (front office, billing, TPA), NABH; DPDP knowledge | Hospital workflows are right; compliance | Workflow validation, compliance checklist, consent text, DPA outline |
| 3 | Solution Architect | 15+ yrs, 8+ in healthcare integrations | System design, data model, integration approach | Architecture, technical decisions, code reviews |
| 4 | Backend & Integration Engineer | 8+ yrs Python/APIs; HIS/billing integrations, HL7/FHIR, ABDM | Automations, billing sync, APIs, webhooks | Working integrations and automations with tests |
| 5 | AI / Prompt Engineer | 6+ yrs NLP/ML, 2+ in LLM products; Indian languages | AI receptionist, insights, AI evals and safety | Prompts, evals, red-team report |
| 6 | Product Designer (UI/UX) | 10+ yrs, healthcare or fintech apps | How every screen looks and works | Design system, staff app, patient app UX |
| 7 | Front-end / Mobile Engineer | 8+ yrs web and PWA | Staff and patient apps | Responsive, accessible, installable apps |
| 8 | QA Lead / Test Automation | 10+ yrs, healthcare or finance QA | Quality gate before every release | Test plan, end-to-end tests, bug reports, release sign-off |
| 9 | Security & Privacy Engineer | 10+ yrs AppSec; OWASP; health data | No data leaks; secure by default | Security review, fixes list, hardening guide |
| 10 | DevOps / SRE | 8+ yrs Linux, Docker, backups, monitoring | Runs reliably at low cost | Docker setup, deploy scripts, backups, monitoring, runbook |
| 11 | Implementation & Customer Success Manager | 10+ yrs hospital software rollouts | Hospital goes live and stays happy | Onboarding plan, staff training SOPs, monthly results report |
| 12 | Sales & Business Development Lead | 10+ yrs selling B2B software to hospitals in India | Winning and growing clients | Pitch, pilot proposal, pricing, objection handling |

## How the roles work together

1. **Head of Product** writes the requirement with acceptance criteria. The **Domain Lead** checks it against how hospitals really work.
2. The **Architect** designs it. **Engineers**, the **Designer** and the **AI Engineer** build it.
3. **Security** reviews it and **QA** tests it. Neither can be skipped.
4. **DevOps** releases it. **Implementation** trains staff, and **Customer Success** reports results monthly.
5. **Sales** sells only what is built or clearly marked as planned.

## Decision rights

| Decision | Decides | Must consult |
|---|---|---|
| What goes in a release | Head of Product | Architect, Domain Lead |
| Hospital workflow and compliance | Domain & Compliance Lead | Head of Product |
| Technology and data design | Solution Architect | Security, DevOps |
| Release go / no-go | QA Lead | Security, Head of Product |
| Price and offer | Sales Lead | Head of Product, founder |
