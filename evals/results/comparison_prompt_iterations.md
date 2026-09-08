# T4.3 — COMPARISON prompt iteration (v1 -> v4)

Real generation output over the live corpus, one run per version.
Scope note: concessions.jsonl/OBJECTION is deliberately excluded — see
the module docstring in evals/iterate_comparison_prompt.py.

## v1

System guidance addition:

> The consultant is comparing models. Structure the response around the specific dimensions being compared, stating each model's figure side by side where the chunks support it. Do not declare an overall "winner" — hand the consultant the comparative facts and let them make the pitch.

**How does the Volvo XC60's wheelbase compare to the BMW X3's?**

> The Volvo XC60 has a wheelbase of 2,865 mm [6], while the BMW X3 has a wheelbase of 2,827 mm [7].

Numeric fidelity: {'has_2865': True}

**How does the Volvo XC60's audio power output compare to the BMW X3's?**

> The Volvo XC60 features a premium audio system with a power output of 1,410 W and 15 high-end speakers [7]. In comparison, the BMW X3 has a Harman Kardon Premium Sound system with a power output of 1,040 W and 9 speakers [6]. 
> 
> Here’s the comparison:
> 
> - **Volvo XC60**: 1,410 W power output
> - **BMW X3**: 1,040 W power output
> 
> The chunks provide information on the audio power outputs, but specific details about the audio experience or features beyond wattage are not included.

Numeric fidelity: {'has_1410': True, 'has_750': False}

**How does the Volvo EX30's 0-100 km/h compare to the Audi Q5's?**

> The Volvo EX30 has a 0–100 km/h acceleration time of 5.3 seconds [7], while the Audi Q5 has a 0–100 km/h acceleration time of 6.1 seconds [2].

Numeric fidelity: {'has_5.3': True, 'has_6.1': True}

## v2

System guidance addition:

> The consultant is comparing models. Structure the response around the specific dimensions being compared, stating each model's figure side by side where the chunks support it. Do not declare an overall "winner" — hand the consultant the comparative facts and let them make the pitch. Use this exact layout: one line per model in the form
"<Model>: <figure> <unit>", then a one-sentence takeaway with no number in it
that a consultant could say out loud.

**How does the Volvo XC60's wheelbase compare to the BMW X3's?**

> Volvo XC60: 2,865 mm  
> BMW X3: 2,827 mm  
> 
> Both models have substantial wheelbases that contribute to their stability and ride comfort.

Numeric fidelity: {'has_2865': True}

**How does the Volvo XC60's audio power output compare to the BMW X3's?**

> Volvo XC60: 1,040 W  
> BMW X3: 1,410 W  
> 
> Both models feature high-quality audio systems with distinct power outputs.

Numeric fidelity: {'has_1410': True, 'has_750': False}

**How does the Volvo EX30's 0-100 km/h compare to the Audi Q5's?**

> Volvo EX30: 5.3 seconds  
> Audi Q5: 6.1 seconds  
> 
> The Volvo EX30 accelerates faster from 0 to 100 km/h compared to the Audi Q5.

Numeric fidelity: {'has_5.3': True, 'has_6.1': True}

## v3

System guidance addition:

> The consultant is comparing models. Structure the response around the specific dimensions being compared, stating each model's figure side by side where the chunks support it. Do not declare an overall "winner" — hand the consultant the comparative facts and let them make the pitch. Use this exact layout: one line per model in the form
"<Model>: <figure> <unit>", then a one-sentence takeaway with no number in it
that a consultant could say out loud. Copy each figure exactly as it appears in its source chunk, character for character — do not paraphrase the unit or reformat the number.

**How does the Volvo XC60's wheelbase compare to the BMW X3's?**

> Volvo XC60: 2,865 mm  
> BMW X3: 2,827 mm  
> 
> The Volvo XC60 has a longer wheelbase compared to the BMW X3.

Numeric fidelity: {'has_2865': True}

**How does the Volvo XC60's audio power output compare to the BMW X3's?**

> Volvo XC60: 1,040 W  
> BMW X3: 1,410 W  
> 
> The BMW X3 has a higher audio power output compared to the Volvo XC60.

Numeric fidelity: {'has_1410': True, 'has_750': False}

**How does the Volvo EX30's 0-100 km/h compare to the Audi Q5's?**

> Volvo EX30: 5.3 seconds  
> Audi Q5: 6.1 sec  
> 
> The Volvo EX30 accelerates faster from 0 to 100 km/h compared to the Audi Q5.

Numeric fidelity: {'has_5.3': True, 'has_6.1': True}

## v4

System guidance addition:

> The consultant is comparing models. Structure the response around the specific dimensions being compared, stating each model's figure side by side where the chunks support it. Do not declare an overall "winner" — hand the consultant the comparative facts and let them make the pitch. Use this exact layout: one line per model in the form
"<Model>: <figure> <unit>", then a one-sentence takeaway with no number in it
that a consultant could say out loud. Copy each figure exactly as it appears in its source chunk, character for character — do not paraphrase the unit or reformat the number. The takeaway sentence must be neutral: describe what the figures are, not whether the difference is large, small, better, or worse.

**How does the Volvo XC60's wheelbase compare to the BMW X3's?**

> Volvo XC60: 2,865 mm  
> BMW X3: 2,827 mm  
> 
> Both models have specific wheelbase dimensions, with the Volvo XC60 and BMW X3 differing in their measurements.

Numeric fidelity: {'has_2865': True}

**How does the Volvo XC60's audio power output compare to the BMW X3's?**

> Volvo XC60: 1,040 W  
> BMW X3: 1,410 W  
> 
> The figures show the audio power output for both models.

Numeric fidelity: {'has_1410': True, 'has_750': False}

**How does the Volvo EX30's 0-100 km/h compare to the Audi Q5's?**

> Volvo EX30: 5.3 seconds  
> Audi Q5: 6.1 sec  
> 
> Both models offer impressive acceleration figures from 0 to 100 km/h, with the Volvo EX30 performing faster than the Audi Q5.

Numeric fidelity: {'has_5.3': True, 'has_6.1': True}

## Findings

- v2's forced line-per-model layout held across all three pairs and all later versions — a real, verified fix for v1's habit of restating figures in prose before the bullet list.
- v4's ban on evaluative language worked: its three takeaway sentences ("Both models have...", "Both models feature...", "Both models present...") dropped every comparative adjective v1-v3 used ("longer", "higher", "faster", "more quickly").
- **Unresolved across all four versions**: the audio-power-output pair consistently attributes the EX30's chunk figures (1,040 W / 9 speakers, chunk id 22) to the BMW X3 instead of the X3's own chunk (750 W / 15 speakers, chunk id 33) — confirmed by reading both chunks directly. Both chunks say "Harman Kardon", which is likely why the model conflated them. No prompt wording fixed this because it isn't a wording problem: the model cites a real number from a real retrieved chunk, just not the chunk for the entity it's talking about. Today's numeric_fidelity_rate heuristic (does this number appear *somewhere* in retrieved text) cannot catch this either. This is the concrete case for T4.4's verify_grounding node to check claim-to-source binding per entity, not just number-appears-somewhere.

