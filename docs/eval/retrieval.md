# Retrieval evaluation

- Run date (UTC): 2026-11-06T17:00:31.377226+00:00
- Commit: 82ef2cf
- Index: champbot-policies
- Embedding model: @cf/baai/bge-m3
- Adapters: WorkersAIEmbedder / VectorizeStore
- Threshold (RETRIEVAL_MIN_SCORE): 0.5

## Summary

| Group | n | hit@1 | hit@5 | MRR | hit@5 after threshold | Mean top score | Min top score |
|---|---|---|---|---|---|---|---|
| overall | 19 | 1.000 | 1.000 | 1.000 | 1.000 | 0.682 | 0.578 |
| en | 14 | 1.000 | 1.000 | 1.000 | 1.000 | 0.684 | 0.606 |
| hi | 5 | 1.000 | 1.000 | 1.000 | 1.000 | 0.674 | 0.578 |

## Per question

| Language | Question | Expected doc | First hit rank | hit@1 | hit@5 | hit@5 after threshold | Top score | Top doc |
|---|---|---|---|---|---|---|---|---|
| en | What is the cabin baggage weight limit in Economy class? | checked-and-cabin-baggage | 1 | ✓ | ✓ | ✓ | 0.676 | checked-and-cabin-baggage |
| en | How many kilograms of checked baggage can I bring in Business class on a domestic flight? | checked-and-cabin-baggage | 1 | ✓ | ✓ | ✓ | 0.713 | checked-and-cabin-baggage |
| en | How do I report damage to my baggage after a flight? | baggage-faq | 1 | ✓ | ✓ | ✓ | 0.706 | baggage-faq |
| en | Can I carry alcohol in my checked baggage on an international flight? | baggage-faq | 1 | ✓ | ✓ | ✓ | 0.650 | baggage-faq |
| en | How early can I check in online for my Air India flight? | check-in | 1 | ✓ | ✓ | ✓ | 0.762 | check-in |
| en | How many hours before departure should I arrive at the airport? | check-in | 1 | ✓ | ✓ | ✓ | 0.668 | check-in |
| en | How can I request a refund for my Air India booking? | cancellation-and-refund | 1 | ✓ | ✓ | ✓ | 0.775 | cancellation-and-refund |
| en | What payment methods does Air India accept? | cancellation-and-refund | 1 | ✓ | ✓ | ✓ | 0.671 | cancellation-and-refund |
| en | How do I request wheelchair assistance for my flight? | special-assistance | 1 | ✓ | ✓ | ✓ | 0.678 | special-assistance |
| en | Can I order a gluten-free meal on my flight? | special-assistance | 1 | ✓ | ✓ | ✓ | 0.606 | special-assistance |
| en | Until which week of pregnancy can I fly with Air India? | infants-and-pregnancy | 1 | ✓ | ✓ | ✓ | 0.628 | infants-and-pregnancy |
| en | What documents do I need to prove my infant's age when travelling? | infants-and-pregnancy | 1 | ✓ | ✓ | ✓ | 0.713 | infants-and-pregnancy |
| en | What should I do if my baggage does not arrive at my destination? | delayed-and-lost-baggage | 1 | ✓ | ✓ | ✓ | 0.687 | delayed-and-lost-baggage |
| en | After how many days is my baggage considered officially lost? | delayed-and-lost-baggage | 1 | ✓ | ✓ | ✓ | 0.647 | delayed-and-lost-baggage |
| hi | घरेलू उड़ान में इकॉनमी क्लास में कितने किलो चेक-इन बैगेज ले जा सकते हैं? | checked-and-cabin-baggage | 1 | ✓ | ✓ | ✓ | 0.686 | checked-and-cabin-baggage |
| hi | एयर इंडिया की फ़्लाइट के लिए ऑनलाइन चेक-इन कब शुरू होता है? | check-in | 1 | ✓ | ✓ | ✓ | 0.704 | check-in |
| hi | मैं अपनी एयर इंडिया बुकिंग का रिफ़ंड कैसे ले सकता हूँ? | cancellation-and-refund | 1 | ✓ | ✓ | ✓ | 0.754 | cancellation-and-refund |
| hi | मुझे अपनी उड़ान के लिए व्हीलचेयर सहायता कैसे मिलेगी? | special-assistance | 1 | ✓ | ✓ | ✓ | 0.578 | special-assistance |
| hi | गर्भावस्था के कितने हफ़्ते तक मैं एयर इंडिया से उड़ान भर सकती हूँ? | infants-and-pregnancy | 1 | ✓ | ✓ | ✓ | 0.649 | infants-and-pregnancy |

## Off-topic queries

| Query | Max score | Kept out |
|---|---|---|
| What's the capital of Australia? | 0.369 | kept out |
| Can you write a short poem about cats? | 0.308 | kept out |
| Why am I getting a Python ModuleNotFoundError? | 0.393 | kept out |
| What's the weather going to be like in Mumbai tomorrow? | 0.399 | kept out |
| Can you recommend a good pizza topping? | 0.358 | kept out |

## Calibration

- Lowest policy top score: 0.578
- Highest off-topic max score: 0.399
- Threshold: 0.5
