# Build Challenges & Technical Obstacles

The hardest part was discovering that a confident model score was not the same as strong
evidence. My first version compared the merchant’s evidence directly with the bank’s claim.
It often understood that the texts were related, but treated a vague delivery scan almost
like a signed proof of delivery. On the working set, that approach produced only 48.1%
precision and would have made costly recommendations. I did not hide the result or keep
tuning a threshold around it. I split verification into two questions: does the evidence
address the claim, and does it contain enough specific detail to substantiate the merchant’s
position? I then added a small synthetic-trained safety gate that is allowed only to demote
a proposed contest to human review. It can never promote a weak case into a contest.

The second challenge was calibration. Raw neural confidence was tightly clustered and did
not behave like a useful business control. A fixed “70% confidence” rule looked precise but
had little operational meaning. I changed the interface to a contest-error budget: the
operator states the error rate they can tolerate, and Coconut selects an operating point
from calibration data while reporting coverage. If the budget cannot be supported, the
system abstains. I also report support and a Wilson confidence interval because six correct
contests out of six is encouraging, but it is still a small synthetic sample. The current
79-case held-out result is 100% observed precision at 20.3% model coverage, with a 61–100%
95% precision interval. I present that as development evidence, not merchant performance.

Keeping decisions correct after data changed was another substantial problem. An operator
could assess a case, edit its evidence, and still see actions belonging to the old decision.
Approvals could also race with a newer assessment. I added evidence fingerprints and stale
decision detection, locked editing and approval when the evidence no longer matched, and
bound every approval to a specific decision ID. Before persisting an action, the backend
rechecks the mutable state. Withdrawals are recorded rather than erasing history, so the
audit trail remains explainable.

Model loading created a very different reliability issue. The local NLI model is large, and
the first request could appear frozen while it loaded. I moved warm-up off the request path,
pinned the exact model revision, added readiness separately from liveness, and retained a
clear failure path when the model or calibration cache is unavailable. Docker was also
unavailable on my development machine because hardware virtualization was disabled, so I
did not claim container verification. I ran the backend and built frontend directly,
documented the limitation, and added local checks that exercise the same application.

Finally, a convincing demo needed prepared examples without turning the product into a
scripted mock. Early presentation data could accumulate edits and approvals between runs,
and resetting a shared database risked destroying normal workspace state. I created a
separate demo entrypoint that overrides credentials before importing the application and
uses a fresh temporary SQLite database. Reset is available only in that process. Payment
creation and webhooks are blocked there, while assessments, evidence explanations,
representment editing and approval auditing use the real application code. Automated tests
prove that demo reset leaves a separate merchant database byte-for-byte untouched, and the
browser test runs all four prepared cases through real inference before testing edit,
approval and reset.

These failures shaped Coconut’s core principle: probabilistic components may interpret
evidence, but deterministic rules control financial actions, uncertainty goes to a person,
and every important state transition remains inspectable.
