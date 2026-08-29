**Problem**

Scaling from a handful of cafés to 85 sites across 5 cities meant refund, rating, sales and complaint data was arriving faster than a 4-person central ops team could manually review it store by store. The team needed to know which locations needed attention first, and why — not another dashboard to stare at.

**Who it's for**

Central ops, deciding where to intervene each period; not customer-facing.

**Options considered**

Started with manual weekly reviews, then a simple 50:50 weighted score across ratings and refunds. Moved to 60:40 refunds:ratings once the data showed why that split was wrong: refunds track almost 1:1 with a poor experience (there's a direct monetary incentive to file one), while ratings are order-level and don't reliably attribute to SHOT specifically — a bad rating can be driven by something outside the café's control. Refunds are also SKU-level, making it easier to trace back to a specific, fixable cause.

Considered a static report but built it as a conversational/slash-command interface instead — the underlying data kept changing and the scoring methodology itself was still new, so the team needed to interrogate the numbers and ask follow-up questions, not just receive a fixed output.

**Decision & trade-off**

Built a shared scoring engine so every question gets the same answer regardless of who asks or how — consistency wasn't reacting to an observed failure, it was a fairness constraint decided upfront. Volume-aware scoring exists for the same reason: it isn't fair to judge a barista doing 25 drinks/hour on the same curve as one doing 10 drinks/shift. Higher volume mechanically produces more mistakes and more mix-up-driven refunds; a low-volume store with the same raw refund count has a real, recurring problem the high-volume one likely doesn't.

**Outcome**

In production, this is what held order ratings at 4.5/5 and retention at 47% (vs. next-best category at 31%) while the network scaled to 85 sites.

**What I would build next**

A store-level trends view — not just "which stores keep flagging" but why: a store repeatedly flagging for the same root cause (same SKU, same defect type) signals something structural worth escalating (training, equipment, recipe spec), while a store flagging for different reasons each time is more likely just noisy and shouldn't be over-indexed on.
