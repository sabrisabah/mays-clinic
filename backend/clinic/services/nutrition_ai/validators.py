"""Validates and normalises a raw AI proposal — run twice, exactly per the
spec: once before the doctor ever sees a preview (ai-suggest), and again
right before saving (ai-apply), against a freshly-fetched Food table each
time so nothing that changed in between (e.g. a food deactivated) can slip
through. Never trusts calorie/macro values the AI reports for a food_id —
those are always recomputed here from the local Food catalogue.

Returns (proposal_or_None, warnings, errors). Any non-empty `errors` means
the whole proposal is rejected — the caller must not display or save it.
`warnings` are safe to show alongside an otherwise-valid proposal.
"""
from datetime import datetime

from .schemas import ALLOWED_MEAL_TYPES, AI_SELECTABLE_MEAL_TYPES, ALLOWED_UNITS, ALLOWED_FOOD_STATES, MAX_ITEM_QUANTITY

AR_LABELS = {"calories": "السعرات", "protein": "البروتين", "carbs": "الكاربوهيدرات", "fat": "الدهون"}

# Best-effort keyword screen for clinically dangerous/overreaching text the
# AI might produce despite the system prompt's rules — flags for doctor
# review rather than silently trusting or blindly rejecting free text.
_DANGEROUS_PHRASES = [
    "أوقف الدواء", "إيقاف الدواء", "توقف عن الدواء", "توقف عن تناول الدواء",
    "قلل جرعة", "زد جرعة", "غيّر الجرعة", "غير الجرعة",
    "تشخيص", "مصاب بـ", "مصابة بـ", "يعاني من مرض", "تعاني من مرض",
    "الخطة معتمدة طبياً", "هذه الخطة معتمدة",
]


def _has_dangerous_text(text):
    text = text or ""
    return any(phrase in text for phrase in _DANGEROUS_PHRASES)


def _split_terms(free_text):
    """Splits a free-text field like food_allergy/disliked_foods ("مكسرات،
    قشطة / بيض") into individual lowercased terms for substring matching.
    Best-effort by nature — these are physician-entered free-text fields,
    not a structured allergen taxonomy."""
    if not free_text:
        return []
    text = free_text.replace("،", ",").replace("/", ",").replace("و ", ",")
    return [t.strip().lower() for t in text.split(",") if t.strip()]


def _text_matches_any(text, terms):
    text = (text or "").lower()
    if not text:
        return False
    return any(term in text for term in terms if term)


def validate_proposal(
    raw,
    *,
    foods_by_id,
    targets,
    allergy_text,
    disliked_text,
    max_meals,
    max_items_per_meal,
    calorie_tolerance_pct,
    macro_tolerance_pct,
    cycle_length_days=1,
):
    """foods_by_id: {int food_id: Food instance} — active foods only, keyed
    exactly as sent to the AI (so an id the AI invents simply won't be
    found here and gets rejected).
    targets: {"calories":..,"protein":..,"carbs":..,"fat":..} grams/kcal
    from the plan (server-side truth, never from the browser) — these are
    PER-DAY targets, so totals are averaged across cycle_length_days below
    before being compared to them.
    allergy_text/disliked_text: Assessment.food_allergy / disliked_foods
    raw strings.
    cycle_length_days: the exact number the AI was told to use for
    day_number (see context.compute_cycle_length_days / generation_request.
    cycle_length_days) — passed in by the caller (views.py) rather than
    trusted from `raw` itself, so a manipulated/hallucinated value in the
    AI's own response can never widen what's accepted here. 1 (the
    pre-existing default) means the original single-repeating-day
    behavior — every meal must have day_number 1 (or omit it)."""
    errors = []
    warnings = []
    cycle_length_days = max(1, int(cycle_length_days or 1))

    if not isinstance(raw, dict):
        return None, [], ["استجابة الذكاء الاصطناعي ليست بصيغة الكائن المتوقعة"]

    summary = raw.get("summary")
    summary = summary if isinstance(summary, str) else ""

    ai_warnings_in = raw.get("warnings")
    ai_warnings = [str(w)[:300] for w in ai_warnings_in if isinstance(w, (str, int, float))] if isinstance(ai_warnings_in, list) else []

    meals_in = raw.get("meals")
    if not isinstance(meals_in, list) or not meals_in:
        return None, warnings, ["لا توجد وجبات ضمن المقترح"]

    # Bound scales with the cycle: up to `effective_max_meals` distinct meal
    # types PER DAY, across up to `cycle_length_days` distinct days.
    effective_max_meals = min(max_meals, len(ALLOWED_MEAL_TYPES) + 5) * cycle_length_days  # sanity backstop
    if len(meals_in) > effective_max_meals:
        errors.append(f"عدد الوجبات المقترحة ({len(meals_in)}) يتجاوز الحد المسموح ({effective_max_meals})")

    allergens = _split_terms(allergy_text)
    disliked = _split_terms(disliked_text)

    seen_meal_types_by_day = {}
    normalized_meals = []
    has_custom_food = False

    for meal_index, m in enumerate(meals_in):
        if not isinstance(m, dict):
            errors.append(f"بيانات الوجبة رقم {meal_index + 1} غير صالحة")
            continue

        meal_type = m.get("meal_type")
        if meal_type not in ALLOWED_MEAL_TYPES:
            errors.append(f"نوع وجبة غير معروف: {meal_type!r}")
            continue
        if meal_type not in AI_SELECTABLE_MEAL_TYPES:
            # سناك1/سناك2 are a fixed clinic-wide default applied at plan
            # creation (views._apply_default_snack), never something the AI
            # is asked to generate (schemas.AI_SELECTABLE_MEAL_TYPES /
            # prompts.py rule 11). The prompt already tells it not to, but
            # a soft instruction alone isn't reliable (see this feature's
            # own history — empty-meals, off-target calories), so any
            # سناك1/سناك2 the AI includes anyway is silently ignored here
            # rather than rejecting the whole proposal over it or bothering
            # the doctor with a warning about something already handled.
            continue

        day_number_raw = m.get("day_number", 1)
        try:
            day_number = int(day_number_raw)
        except (TypeError, ValueError):
            day_number = None
        if day_number is None or not (1 <= day_number <= cycle_length_days):
            errors.append(
                f"رقم يوم غير صالح للوجبة {meal_type}: {day_number_raw!r} "
                f"(يجب أن يكون بين 1 و{cycle_length_days})"
            )
            continue

        seen_meal_types = seen_meal_types_by_day.setdefault(day_number, set())
        if meal_type in seen_meal_types:
            errors.append(f"تكرار نوع الوجبة ({meal_type}) في نفس اليوم ({day_number}) ضمن المقترح")
            continue
        seen_meal_types.add(meal_type)

        time_raw = m.get("time")
        parsed_time = None
        if time_raw:
            try:
                parsed_time = datetime.strptime(str(time_raw), "%H:%M").time()
            except ValueError:
                errors.append(f"وقت غير صالح للوجبة {meal_type}: {time_raw!r} (يجب أن يكون بصيغة HH:MM)")

        items_in = m.get("items")
        if not isinstance(items_in, list) or not items_in:
            errors.append(f"الوجبة {meal_type} فارغة — يجب أن تحتوي على صنف واحد على الأقل")
            continue
        if len(items_in) > max_items_per_meal:
            errors.append(f"عدد الأصناف في وجبة {meal_type} ({len(items_in)}) يتجاوز الحد المسموح ({max_items_per_meal})")

        normalized_items = []
        seen_item_keys = set()
        for item_index, it in enumerate(items_in):
            if not isinstance(it, dict):
                errors.append(f"بيانات صنف غير صالحة في وجبة {meal_type}")
                continue

            food_id = it.get("food_id")
            food = None
            if food_id not in (None, ""):
                try:
                    food_id = int(food_id)
                except (TypeError, ValueError):
                    errors.append(f"معرّف صنف غير صالح في وجبة {meal_type}: {food_id!r}")
                    continue
                food = foods_by_id.get(food_id)
                if food is None:
                    errors.append(f"صنف غذائي غير موجود أو غير نشط (food_id={food_id}) في وجبة {meal_type}")
                    continue

            custom_name = (it.get("custom_food_name") or "").strip()
            if food is None and not custom_name:
                errors.append(f"صنف بلا food_id ولا اسم مخصص في وجبة {meal_type}")
                continue

            dedup_key = ("food", food.id) if food else ("custom", custom_name.lower())
            if dedup_key in seen_item_keys:
                errors.append(f"صنف مكرر داخل وجبة {meal_type}: {food.name if food else custom_name}")
                continue
            seen_item_keys.add(dedup_key)

            try:
                quantity = float(it.get("quantity"))
            except (TypeError, ValueError):
                errors.append(f"كمية غير صالحة في وجبة {meal_type} (الصنف رقم {item_index + 1})")
                continue
            if quantity <= 0 or quantity > MAX_ITEM_QUANTITY:
                errors.append(f"كمية غير معقولة ({quantity}) في وجبة {meal_type}")
                continue

            unit = it.get("unit") or (food.unit if food else "غم")
            if unit not in ALLOWED_UNITS:
                errors.append(f"وحدة غير مدعومة ({unit!r}) في وجبة {meal_type}")
                continue

            food_state = (it.get("food_state") or "").strip()
            if food_state and food_state not in ALLOWED_FOOD_STATES:
                errors.append(f"حالة طعام غير مدعومة ({food_state!r}) في وجبة {meal_type}")
                continue

            name_for_check = food.name if food else custom_name
            alt_text = str(it.get("alternative_text") or "")[:255]
            instructions = str(it.get("instructions") or "")[:255]

            if _text_matches_any(name_for_check, allergens) or _text_matches_any(alt_text, allergens):
                errors.append(f"صنف يحتوي على مادة ضمن حساسيات المريض المسجّلة: {name_for_check}")
                continue
            if _text_matches_any(name_for_check, disliked):
                warnings.append(f"الصنف \"{name_for_check}\" مدرج ضمن الأطعمة غير المفضّلة للمريض — تحقق قبل الاعتماد")

            if _has_dangerous_text(instructions) or _has_dangerous_text(alt_text):
                warnings.append(f"تعليمات الصنف \"{name_for_check}\" تحتوي عبارات تحتاج مراجعة الطبيب (تشخيص/تعديل دواء) قبل الاعتماد")

            is_custom = food is None
            has_custom_food = has_custom_food or is_custom

            order_raw = it.get("order")
            try:
                order = int(order_raw)
            except (TypeError, ValueError):
                order = len(normalized_items)

            normalized_items.append({
                "food_id": food.id if food else None,
                "custom_food_name": "" if food else custom_name[:200],
                "is_custom": is_custom,
                "quantity": round(quantity, 2),
                "unit": unit,
                "food_state": food_state,
                "alternative_text": alt_text,
                "instructions": instructions,
                "patient_visible": bool(it.get("patient_visible", True)),
                "order": order,
            })

        if not normalized_items:
            continue
        normalized_meals.append({
            "day_number": day_number,
            "meal_type": meal_type,
            "time": time_raw if parsed_time else None,
            "order": ALLOWED_MEAL_TYPES.index(meal_type),
            "items": sorted(normalized_items, key=lambda x: x["order"]),
        })

    if errors:
        return None, warnings, errors
    if not normalized_meals:
        return None, warnings, ["لم يتبقَّ أي وجبة صالحة بعد التحقق من المقترح"]

    # Per-day totals first (targets are inherently PER DAY — calorie_target
    # etc. — so a multi-day cycle must never just sum every day together,
    # or a 7-day proposal would look like a ~700% calorie overshoot). Then
    # "totals"/"comparison" below are the AVERAGE across the distinct days
    # actually present, exactly matching plain single-day behavior when
    # cycle_length_days == 1 (average of one day == that day).
    daily_totals = {}
    for meal in normalized_meals:
        day_totals = daily_totals.setdefault(meal["day_number"], {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0})
        for it in meal["items"]:
            if it["is_custom"]:
                continue
            food = foods_by_id[it["food_id"]]
            day_totals["calories"] += food.calories_per_unit * it["quantity"]
            day_totals["protein"] += food.protein_per_unit * it["quantity"]
            day_totals["carbs"] += food.carbs_per_unit * it["quantity"]
            day_totals["fat"] += food.fat_per_unit * it["quantity"]

    if has_custom_food:
        warnings.append("تحتوي الخطة على أصناف مخصصة بدون قيم غذائية محسوبة — راجعها يدوياً أو أضفها إلى قائمة الأطعمة قبل الاعتماد")

    # Server-side per-day calorie correction. In practice, trusting the
    # AI's own arithmetic to land each day of a multi-day cycle within
    # calorie_tolerance_pct turned out unreliable — real proposals came
    # back with day-to-day swings of roughly -30% to +30% around
    # calorie_target despite an explicit prompt rule requiring each day to
    # independently approximate it (prompts.py rule 12's "كل يوم على حدة"
    # addendum). Rather than accepting an imprecise proposal or rejecting
    # it outright, scale every real-food item's quantity within a day by
    # ONE day-wide factor so that day's calorie total lands on
    # calorie_target — the AI still decides WHICH foods to use and how the
    # days differ from each other (its actual contribution); only the
    # final amounts get corrected. Since every nutrition value is linear
    # in quantity, scaling by a single factor also moves protein/carbs/fat
    # by the same proportion, preserving whatever macro balance the AI's
    # food choices already had for that day rather than distorting it.
    # Custom items (is_custom — no catalogue nutrition) are left exactly
    # as the AI wrote them and excluded from the scaling factor itself,
    # same as they're already excluded from daily_totals above.
    calorie_target_for_scaling = targets.get("calories") or 0
    if calorie_target_for_scaling:
        meals_by_day = {}
        for meal in normalized_meals:
            meals_by_day.setdefault(meal["day_number"], []).append(meal)
        for day_number, day_meals in meals_by_day.items():
            day_calories = daily_totals.get(day_number, {}).get("calories", 0)
            if day_calories <= 0:
                continue  # only custom items (or none) that day — nothing to scale
            scale = calorie_target_for_scaling / day_calories
            if abs(scale - 1) < 0.01:
                continue  # already essentially on target — don't perturb needlessly
            for meal in day_meals:
                for item in meal["items"]:
                    if item["is_custom"]:
                        continue
                    item["quantity"] = round(min(item["quantity"] * scale, MAX_ITEM_QUANTITY), 1)
            recomputed = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
            for meal in day_meals:
                for item in meal["items"]:
                    if item["is_custom"]:
                        continue
                    food = foods_by_id[item["food_id"]]
                    recomputed["calories"] += food.calories_per_unit * item["quantity"]
                    recomputed["protein"] += food.protein_per_unit * item["quantity"]
                    recomputed["carbs"] += food.carbs_per_unit * item["quantity"]
                    recomputed["fat"] += food.fat_per_unit * item["quantity"]
            daily_totals[day_number] = recomputed

    num_days = len(daily_totals) or 1
    totals = {
        key: sum(d[key] for d in daily_totals.values()) / num_days
        for key in ("calories", "protein", "carbs", "fat")
    }

    comparison = {}
    for key, tol in (
        ("calories", calorie_tolerance_pct), ("protein", macro_tolerance_pct),
        ("carbs", macro_tolerance_pct), ("fat", macro_tolerance_pct),
    ):
        target = targets.get(key) or 0
        actual = round(totals[key], 1)
        diff = round(actual - target, 1)
        diff_pct = round((diff / target * 100), 1) if target else 0.0
        comparison[key] = {"target": target, "actual": actual, "diff": diff, "diff_pct": diff_pct}
        if target and abs(diff_pct) > tol:
            warnings.append(
                (f"متوسط {AR_LABELS[key]} عبر أيام الدورة" if num_days > 1 else AR_LABELS[key])
                + f" يختلف عن الهدف ({diff_pct:+.1f}%) بأكثر من الحد المسموح ({tol}%) — "
                f"الفعلي {actual} مقابل الهدف {target}"
            )

    # Flag any INDIVIDUAL day whose calories stray far from target, even if
    # the cycle's average (checked above) looks fine — a doctor should know
    # if e.g. day 3 of 7 is unusually light/heavy, not just the average.
    if num_days > 1:
        calorie_target = targets.get("calories") or 0
        if calorie_target:
            for day_number in sorted(daily_totals):
                day_calories = round(daily_totals[day_number]["calories"], 1)
                day_diff_pct = round((day_calories - calorie_target) / calorie_target * 100, 1)
                if abs(day_diff_pct) > calorie_tolerance_pct:
                    warnings.append(
                        f"اليوم {day_number} من الدورة: السعرات ({day_calories}) تختلف عن الهدف اليومي "
                        f"({day_diff_pct:+.1f}%) بأكثر من الحد المسموح ({calorie_tolerance_pct}%)"
                    )

    proposal = {
        "summary": summary,
        "cycle_length_days": num_days,
        "meals": normalized_meals,
        "daily_totals": {str(k): {mk: round(mv, 1) for mk, mv in v.items()} for k, v in daily_totals.items()},
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "comparison": comparison,
        "has_custom_foods": has_custom_food,
    }
    all_warnings = list(dict.fromkeys(ai_warnings + warnings))
    return proposal, all_warnings, []
