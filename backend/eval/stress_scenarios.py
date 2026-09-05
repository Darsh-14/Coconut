"""Authored synthetic facts and assumed outcomes, never model-generated labels.

Each reason has two defensible bundles, two insufficient bundles and one merchant
error. These are scenario assumptions, not observed bank outcomes. Parameterised
variants of a bundle are correlated and must be reported as the same family.
"""

# Bundle entries are (evidence type, text). Templates use fictional references.
SCENARIOS = {
    "goods_not_received": {
        "claim": "The buyer disputes receipt of the parcel for purchase {ref}.",
        "bundles": [
            [
                ("delivery_proof", "Carrier record for {ref} contains the named buyer's signature and a one-time delivery code supplied by the buyer on {date}. The parcel was handed to that buyer at the order address."),
                ("communication_log", "In a message linked to {ref}, the buyer confirms receiving the complete parcel on {date} and asks only about the warranty."),
            ],
            [
                ("delivery_proof", "Store collection record {ref} was signed by the buyer after staff checked the order collection code and identity document on {date}."),
                ("communication_log", "The buyer's authenticated account message says they collected purchase {ref} in person on {date} and all items were present."),
            ],
            [
                ("delivery_proof", "The carrier page for {ref} says delivered to the building lobby on {date}. No recipient name, signature, OTP or handover photograph is available."),
                ("order_history", "Purchase {ref} was packed and dispatched. The warehouse has no record of who collected the parcel from the lobby."),
            ],
            [
                ("delivery_proof", "The delivery document offered for {ref} has a different apartment number and a recipient name that does not match the buyer. The carrier has not explained the mismatch."),
                ("communication_log", "Support told the buyer that the parcel for {ref} was delivered, relying only on that mismatched document. The buyer denies receiving it."),
            ],
            [
                ("delivery_proof", "The carrier confirms parcel {ref} was lost before delivery on {date}; no replacement was dispatched."),
                ("communication_log", "The merchant acknowledged to the buyer that purchase {ref} never arrived and that the payment of Rs {amount} has not been refunded."),
            ],
        ],
    },
    "credit_not_processed": {
        "claim": "The buyer says the agreed refund for purchase {ref} remains unpaid.",
        "bundles": [
            [
                ("order_history", "The acquirer credit ledger links refund {ref} for Rs {amount} to the original payment. The issuing bank accepted the full credit on {date}; there was no reversal."),
                ("communication_log", "The buyer's authenticated message confirms the full Rs {amount} refund for {ref} appeared on their account statement on {date}."),
            ],
            [
                ("other", "The issuing bank's reconciliation response identifies refund {ref}, confirms Rs {amount} was posted on {date}, and matches the disputed payment."),
                ("order_history", "The processor statement shows the full credit for {ref} settled on {date} with a traceable acquirer reference and no failed or reversed status."),
            ],
            [
                ("order_history", "The admin page marks refund {ref} as requested on {date}. No processor credit, bank reference or settlement status is attached."),
                ("communication_log", "Support says a refund for {ref} should arrive soon. The message is a promise, not confirmation that money was credited."),
            ],
            [
                ("other", "The settlement proof attached to refund {ref} belongs to another payment and has a different customer reference. No matching refund trace is available."),
                ("communication_log", "Support reused that settlement attachment when responding about {ref}; the buyer says the credit is still absent."),
            ],
            [
                ("order_history", "Refund {ref} failed at the processor on {date}. The ledger shows no later credit or replacement refund for Rs {amount}."),
                ("communication_log", "The merchant confirms the agreed refund for {ref} has not been paid because the refund job failed."),
            ],
        ],
    },
    "duplicate_charge": {
        "claim": "The buyer says purchase {ref} resulted in two charges for one order.",
        "bundles": [
            [
                ("order_history", "For {ref}, the processor ledger shows exactly one settled capture of Rs {amount}. The second entry is an uncaptured authorisation released on {date}."),
                ("other", "The issuing bank confirms only one final debit for {ref}; the temporary hold was released and did not become another payment."),
            ],
            [
                ("order_history", "The two payments associated with inquiry {ref} map to two separately placed purchases, each with a distinct invoice and fulfilled basket."),
                ("communication_log", "The buyer's authenticated message acknowledges placing both purchases in inquiry {ref} and receiving each separately; neither was a repeat billing of one order."),
            ],
            [
                ("order_history", "Two Rs {amount} ledger rows appear for {ref}. The export omits capture identifiers and final settlement status, so it cannot establish whether one is just a hold."),
                ("communication_log", "Support assumes the second row for {ref} is temporary but has not checked with the processor or obtained a hold-release record."),
            ],
            [
                ("order_history", "Two order numbers were allocated to {ref}, with the same basket and address. There is no second checkout record or separate dispatch."),
                ("other", "The merchant's unsigned note attributes the second charge for {ref} to a second purchase, but no customer authorisation for that purchase is attached."),
            ],
            [
                ("order_history", "The payment log for {ref} contains two settled captures of Rs {amount} against the same order. Neither has been reversed."),
                ("communication_log", "The merchant acknowledges a checkout retry charged {ref} twice and confirms only one order was fulfilled."),
            ],
        ],
    },
    "subscription_cancelled": {
        "claim": "The subscriber says purchase {ref} was billed after cancellation took effect.",
        "bundles": [
            [
                ("order_history", "Billing audit {ref} shows the disputed renewal completed before the customer submitted cancellation. The timestamped cancellation receipt explicitly ends billing from the next cycle."),
                ("communication_log", "The subscriber's authenticated message about {ref} acknowledges cancelling after that renewal and confirms the disputed cycle was used."),
            ],
            [
                ("order_history", "After cancellation, the subscriber explicitly reactivated subscription {ref}, accepted the displayed Rs {amount} price and completed checkout on {date}. The disputed charge belongs to that new purchase."),
                ("communication_log", "The subscriber confirms in an authenticated message that they restarted {ref} and authorised the new purchase on {date}."),
            ],
            [
                ("order_history", "The account page for {ref} displays active, but the export contains no cancellation history or timestamp for the status."),
                ("communication_log", "Support asserts that {ref} was not cancelled. The earlier cancellation request mailbox could not be searched and no receipt is provided."),
            ],
            [
                ("order_history", "A cancellation and renewal for {ref} share the date {date}, but timestamps and time zones were removed from the export. Their order cannot be established."),
                ("other", "The terms supplied for {ref} describe a renewal cutoff, but there is no record showing when this subscriber accepted those terms."),
            ],
            [
                ("order_history", "The cancellation receipt for {ref} ended the subscription before the disputed renewal. A billing defect nevertheless collected Rs {amount}; no refund followed."),
                ("communication_log", "The merchant confirms {ref} was cancelled before renewal and apologises for charging after cancellation."),
            ],
        ],
    },
    "goods_not_as_described": {
        "claim": "The buyer says the item in purchase {ref} differs materially from the agreed specification.",
        "bundles": [
            [
                ("order_history", "The saved checkout for {ref} specifies the exact item model and features supplied. Serial-linked inspection photographs show those features on the dispatched unit."),
                ("communication_log", "The buyer's message about {ref} confirms the model and features match the accepted listing and says the return is solely due to a change of preference."),
            ],
            [
                ("other", "An independent dated inspection of the returned unit for {ref}, with matching serial number and inspector signature, verifies every disputed specification matches the original listing."),
                ("order_history", "The versioned listing accepted for {ref} and the serial-linked dispatch record match the unit and specifications in that independent inspection."),
            ],
            [
                ("other", "The merchant's internal inspection of {ref} says the item is fine. It is unsigned, undated and does not identify the unit tested."),
                ("order_history", "The current listing for {ref} matches the merchant's description, but the version shown to the buyer at checkout was not retained."),
            ],
            [
                ("other", "A quality certificate is attached to {ref}, but it covers a different model. No inspection of the actual disputed item is available."),
                ("communication_log", "Support cites that certificate as proof of compliance for {ref}, without responding to the buyer's photographs of different specifications."),
            ],
            [
                ("order_history", "The archived checkout specification for {ref} promises a feature that the dispatch record confirms is absent from the supplied model."),
                ("communication_log", "The merchant acknowledges shipping the wrong specification for {ref} and confirms no replacement or refund has been provided."),
            ],
        ],
    },
    "unrecognized_transaction": {
        "claim": "The cardholder denies authorising the payment linked to purchase {ref}.",
        "bundles": [
            [
                ("device_signal", "Issuer authentication for {ref} completed a successful challenge on the cardholder's registered device and number, bound to this exact payment and amount of Rs {amount}."),
                ("communication_log", "The cardholder's authenticated message explicitly confirms personally placing and paying for {ref}; the unfamiliar statement descriptor caused the initial query."),
            ],
            [
                ("order_history", "The signed in-person payment receipt for {ref} matches the cardholder identity checked at collection and records the same amount, item and payment reference."),
                ("communication_log", "The cardholder confirms in an authenticated message that they personally paid for and collected {ref} on {date}."),
            ],
            [
                ("device_signal", "Payment {ref} used an IP address in the buyer's city. No authenticated device continuity or issuer challenge result is available."),
                ("order_history", "The checkout for {ref} contains the cardholder's name and address; there is no independent record that the cardholder submitted it."),
            ],
            [
                ("device_signal", "The merchant supplied a successful authentication log for another payment as support for {ref}. It cannot be linked to the disputed amount or checkout."),
                ("communication_log", "An unverified email address said {ref} was authorised. The merchant cannot link its sender to the cardholder."),
            ],
            [
                ("device_signal", "The issuer investigation identifies payment {ref} as made using a compromised credential. The challenge failed and there is no cardholder authorisation."),
                ("communication_log", "The merchant accepts the issuer's finding that {ref} was unauthorised and confirms the charge has not been refunded."),
            ],
        ],
    },
}

LABELS = ("contest_win", "contest_win", "contest_loss", "contest_loss", "should_accept")
RATIONALES = (
    "Two transaction-linked records substantiate the merchant's position in this fictional scenario.",
    "Independent or customer-confirmed corroboration substantiates the merchant's position.",
    "Essential substantiation is missing; contest_loss is an assumed benchmark outcome, not a bank decision.",
    "The supplied proof is mismatched or unresolved; contest_loss is an assumed benchmark outcome.",
    "The fictional records explicitly establish merchant error or an unauthorised payment.",
)
