"""The ten scripted moments of the demo match, with their facts and trilingual texts.

Texts obey the agent rules: every number comes from the moment metrics, every claim cites events.
"""

from __future__ import annotations

from mock_script import (
    AWAY,
    FT_T,
    HOME,
    HT_T,
    PRESSURE_EVENTS,
    RECOVERIES,
    SPELL_SHOTS,
    TURNOVERS,
    Scripted,
    Text,
    t1,
    t2,
)
from pitchmind_contracts import (
    InsightKind,
    MetricName,
    MomentKind,
    OverlaySlot,
)

MOMENTS: list[Scripted] = [
    Scripted(
        1,
        t1(9, 12),
        MomentKind.GOAL,
        AWAY,
        ["A9", "A10"],
        1.0,
        {"xg": 0.38, "shot_speed_kmh": 104.2, "pass_difficulty": 0.71, "home_goals": 0, "away_goals": 1},
        "Goal for Harbour United: Halvorsen scores after 9 minutes.",
        [(["m1_pass"], ["pass_difficulty"]), (["m1_shot", "m1_goal"], ["xg", "shot_speed_kmh"])],
        {
            "analyst_en": Text(
                "Harbour strike first through Halvorsen",
                "Albers splits the North City back line with a pass rated 0.71 for difficulty, and "
                "Halvorsen finishes at 104.2 km/h. The chance was worth 0.38 xG.",
                [
                    "Albers' pass had a difficulty rating of 0.71.",
                    "Halvorsen's shot was a 0.38 xG chance, struck at 104.2 km/h.",
                ],
            ),
            "casual_ar": Text(
                "هدف مبكر لهاربور يونايتد",
                "بداية صعبة لنورث سيتي: تمريرة ذكية من Albers وضعت Halvorsen أمام المرمى، "
                "فسدد بقوة 104.2 كم/س. ما زالت المباراة في دقائقها الأولى.",
                ["تمريرة Albers كانت صعبة التنفيذ (0.71).", "تسديدة Halvorsen بلغت سرعتها 104.2 كم/س."],
            ),
            "beginner_fr": Text(
                "But de Harbour United !",
                "Halvorsen marque après 9 minutes. Le « xG » (buts attendus) de son tir était de 0,38 : "
                "plus ce chiffre est élevé, plus l'occasion était facile.",
                ["La passe d'Albers était difficile (0,71 sur 1).", "Le tir de Halvorsen valait 0,38 xG."],
            ),
        },
        insight_kind=InsightKind.COMMENTARY,
        priority=90,
        duration=8.0,
        metric=(MetricName.XG, "xg", None),
    ),
    Scripted(
        2,
        t1(27, 40),
        MomentKind.PRESSURE_SURGE,
        HOME,
        ["H9", "H8", "H6"],
        0.7,
        {
            "pressure_index_before": 0.38,
            "pressure_index_after": 0.74,
            "window_min": 5,
            "recoveries_opp_half": 4,
            "possession_pct_window": 68,
        },
        "North City's pressure index rose from 0.38 to 0.74 in 5 minutes.",
        [
            (PRESSURE_EVENTS, ["pressure_index_before", "pressure_index_after", "window_min"]),
            (RECOVERIES, ["recoveries_opp_half"]),
            (PRESSURE_EVENTS, ["possession_pct_window"]),
        ],
        {
            "analyst_en": Text(
                "North City's press takes hold",
                "North City's pressure index has jumped from 0.38 to 0.74 in 5 minutes, with 4 ball "
                "recoveries in Harbour's half and 68% of the possession in that window.",
                [
                    "Pressure index rose from 0.38 to 0.74 over 5 minutes.",
                    "4 ball recoveries in Harbour's half.",
                    "68% possession during the spell.",
                ],
            ),
            "casual_ar": Text(
                "نورث سيتي يضغط بقوة!",
                "فريقك استعاد الكرة 4 مرات في نصف ملعب الخصم خلال 5 دقائق، واستحوذ على 68% من الكرة. "
                "الضغط يتصاعد بوضوح.",
                [
                    "مؤشر الضغط ارتفع من 0.38 إلى 0.74.",
                    "4 استعادات للكرة في نصف ملعب هاربور.",
                    "استحواذ بنسبة 68% خلال هذه الفترة.",
                ],
            ),
            "beginner_fr": Text(
                "North City met la pression",
                "« Presser », c'est attaquer le porteur du ballon pour le récupérer vite. North City l'a "
                "fait si bien qu'il a récupéré le ballon 4 fois dans le camp adverse en 5 minutes.",
                [
                    "L'indice de pression est passé de 0,38 à 0,74.",
                    "4 ballons récupérés dans le camp adverse.",
                    "68 % de possession pendant cette période.",
                ],
            ),
        },
        metric=(MetricName.PRESSURE_INDEX, "pressure_index_after", None),
    ),
    Scripted(
        3,
        t1(33, 5),
        MomentKind.BIG_CHANCE,
        HOME,
        ["H10", "A1", "H7"],
        0.8,
        {"xg": 0.41, "shot_speed_kmh": 112.3},
        "Big chance for North City: Haddad's shot is saved by Sandvik.",
        [(["m3_pass", "m3_shot"], ["xg", "shot_speed_kmh"]), (["m3_save"], [])],
        {
            "analyst_en": Text(
                "Haddad denied by Sandvik",
                "Whitcombe finds Haddad between the lines; his 112.3 km/h strike was a 0.41 xG chance, "
                "kept out by Sandvik.",
                ["Haddad's shot: 0.41 xG at 112.3 km/h.", "Sandvik made the save."],
            ),
            "casual_ar": Text(
                "يا لها من فرصة!",
                "Haddad سدد كرة قوية بسرعة 112.3 كم/س، لكن الحارس Sandvik أنقذها ببراعة. "
                "نورث سيتي كان قريباً جداً من التعادل.",
                ["تسديدة Haddad: سرعة 112.3 كم/س وفرصة تسجيل 0.41.", "الحارس Sandvik تصدى للكرة."],
            ),
            "beginner_fr": Text(
                "Énorme arrêt de Sandvik",
                "Haddad frappe à 112,3 km/h. Cette occasion valait 0,41 xG, une vraie occasion de but, "
                "mais le gardien Sandvik a réussi l'arrêt.",
                ["Le tir de Haddad valait 0,41 xG, à 112,3 km/h.", "Sandvik a arrêté le tir."],
            ),
            "player_h10": Text(
                "Big moment for Haddad",
                "Rayan Haddad forced a big save with a 112.3 km/h shot, a 0.41 xG chance.",
                ["Haddad's shot: 0.41 xG at 112.3 km/h.", "Sandvik made the save."],
            ),
        },
        priority=75,
        metric=(MetricName.XG, "xg", None),
    ),
    Scripted(
        4,
        HT_T,
        MomentKind.PHASE,
        None,
        ["A9", "H10"],
        0.9,
        {
            "home_goals": 0,
            "away_goals": 1,
            "home_xg": 0.71,
            "away_xg": 0.52,
            "home_shots": 6,
            "away_shots": 4,
            "home_pressure_index_peak_half": 0.74,
        },
        "Half-time: North City 0-1 Harbour United.",
        [
            (["m1_goal"], ["home_goals", "away_goals"]),
            (["m1_shot", "m3_shot"], ["home_xg", "away_xg"]),
            (["ht"], ["home_shots", "away_shots"]),
            (["m2_p4"], ["home_pressure_index_peak_half"]),
        ],
        {
            "analyst_en": Text(
                "Half-time: Harbour lead, North City lead the xG",
                "Harbour lead 1-0 through Halvorsen's 9th-minute goal, but North City lead the xG 0.71 to "
                "0.52 and the shot count 6 to 4. Their press, peaking at a 0.74 pressure index, produced "
                "Haddad's chance, saved by Sandvik.",
                [
                    "Score 0-1 after Halvorsen's goal.",
                    "xG: North City 0.71, Harbour 0.52.",
                    "Shots: 6 to 4 for North City.",
                    "Pressure index peaked at 0.74.",
                ],
            ),
            "casual_ar": Text(
                "نهاية الشوط الأول: تأخر رغم الأفضلية",
                "نورث سيتي متأخر 0-1، لكنه كان الأخطر: 6 تسديدات مقابل 4، وأهداف متوقعة 0.71 مقابل 0.52. "
                "الضغط العالي صنع أفضل فرصة لـ Haddad، وأنقذها الحارس.",
                [
                    "النتيجة 0-1 بعد هدف Halvorsen.",
                    "الأهداف المتوقعة: 0.71 مقابل 0.52.",
                    "التسديدات: 6 مقابل 4 لنورث سيتي.",
                    "مؤشر الضغط وصل إلى 0.74.",
                ],
            ),
            "beginner_fr": Text(
                "Mi-temps : 0-1",
                "Harbour United mène grâce au but de Halvorsen. Pourtant, North City a tiré plus souvent "
                "(6 tirs contre 4) et a eu les meilleures occasions selon le xG (0,71 contre 0,52). "
                "Le score ne reflète pas toujours le jeu.",
                [
                    "Score : 0-1 après le but de Halvorsen.",
                    "xG : 0,71 pour North City, 0,52 pour Harbour.",
                    "Tirs : 6 contre 4 pour North City.",
                    "L'indice de pression a atteint 0,74.",
                ],
            ),
        },
        insight_kind=InsightKind.RECAP,
        slot=OverlaySlot.RECAP_CARD,
        priority=80,
        duration=20.0,
    ),
    Scripted(
        5,
        t2(58, 30),
        MomentKind.MOMENTUM_SWING,
        HOME,
        ["H9", "H11", "H7"],
        0.65,
        {"momentum_before": -0.35, "momentum_after": 0.52, "home_shots_last_10min": 4, "window_min": 8},
        "Momentum has swung to North City: 4 shots in the last 10 minutes.",
        [(SPELL_SHOTS, ["home_shots_last_10min"]), (["m5_s1", "m5_s4"], ["momentum_before", "momentum_after"])],
        {
            "analyst_en": Text(
                "Momentum flips to North City",
                "Match momentum has swung from -0.35 to +0.52 in 8 minutes, with North City taking 4 shots "
                "in the last 10 minutes.",
                ["4 North City shots in 10 minutes.", "Momentum moved from -0.35 to 0.52."],
            ),
            "casual_ar": Text(
                "الكفة تميل لفريقك",
                "نورث سيتي سيطر على المباراة من جديد: 4 تسديدات في آخر 10 دقائق، ومؤشر الزخم انقلب لصالحه.",
                ["4 تسديدات لنورث سيتي في 10 دقائق.", "مؤشر الزخم انتقل من -0.35 إلى 0.52."],
            ),
            "beginner_fr": Text(
                "Le vent tourne",
                "Le « momentum » mesure quelle équipe domine en ce moment. Il est passé du côté de "
                "North City, qui a tiré 4 fois en 10 minutes.",
                ["4 tirs de North City en 10 minutes.", "Le momentum est passé de -0,35 à 0,52."],
            ),
        },
        metric=(MetricName.MOMENTUM, "momentum_after", None),
    ),
    Scripted(
        6,
        t2(61, 10),
        MomentKind.GOAL,
        HOME,
        ["H9", "H10"],
        1.0,
        {
            "pass_difficulty": 0.83,
            "pass_distance_m": 27.5,
            "xg": 0.29,
            "shot_speed_kmh": 98.7,
            "home_goals": 1,
            "away_goals": 1,
            "home_shots_prev_10min": 4,
        },
        "Goal for North City: Kaya equalises, assisted by Haddad. 1-1.",
        [
            (["m6_pass"], ["pass_difficulty", "pass_distance_m"]),
            (["m6_shot", "m6_goal"], ["xg", "shot_speed_kmh"]),
            (SPELL_SHOTS, ["home_shots_prev_10min"]),
        ],
        {
            "analyst_en": Text(
                "Kaya levels from Haddad's through ball",
                "Haddad's 27.5 m through ball under pressure carried a 0.83 difficulty rating; Kaya "
                "converted the 0.29 xG chance at 98.7 km/h. The equaliser follows 4 shots in 10 minutes.",
                [
                    "Haddad's pass: 27.5 m, difficulty 0.83.",
                    "Kaya's finish: 0.29 xG at 98.7 km/h.",
                    "4 shots in the previous 10 minutes.",
                ],
            ),
            "casual_ar": Text(
                "تعادل! Kaya يسجل",
                "تمريرة ساحرة من Haddad تحت الضغط، وKaya يسدد في الشباك بسرعة 98.7 كم/س. 1-1 والمباراة تشتعل!",
                [
                    "تمريرة Haddad: 27.5 متر وصعوبة 0.83.",
                    "تسديدة Kaya بسرعة 98.7 كم/س.",
                    "4 تسديدات في الدقائق العشر السابقة.",
                ],
            ),
            "beginner_fr": Text(
                "Égalisation de North City !",
                "Haddad a réussi une passe très difficile (0,83 sur 1) entre les défenseurs, et Kaya a "
                "marqué. Score : 1-1.",
                [
                    "Passe de Haddad : 27,5 m, difficulté 0,83.",
                    "Tir de Kaya : 0,29 xG à 98,7 km/h.",
                    "4 tirs dans les 10 minutes précédentes.",
                ],
            ),
            "player_h10": Text(
                "Haddad's assist",
                "Rayan Haddad delivered the assist: a 27.5 m through ball under pressure with a 0.83 "
                "difficulty rating.",
                [
                    "Haddad's pass: 27.5 m, difficulty 0.83.",
                    "Kaya's finish: 0.29 xG at 98.7 km/h.",
                    "4 shots in the previous 10 minutes.",
                ],
            ),
        },
        insight_kind=InsightKind.COMMENTARY,
        priority=90,
        duration=8.0,
        metric=(MetricName.PASS_DIFFICULTY, "pass_difficulty", None),
    ),
    Scripted(
        8,
        t2(80, 45),
        MomentKind.CONTROL_SHIFT,
        None,
        [],
        0.6,
        {
            "control_chaos_before": 0.31,
            "control_chaos_after": 0.78,
            "rhythm_before_epm": 14,
            "rhythm_after_epm": 23,
            "turnovers_last_5min": 9,
        },
        "The match has turned chaotic: control-chaos index up from 0.31 to 0.78.",
        [
            (TURNOVERS, ["turnovers_last_5min", "control_chaos_before", "control_chaos_after"]),
            (["m8_pc1", "m8_pc4"], ["rhythm_before_epm", "rhythm_after_epm"]),
        ],
        {
            "analyst_en": Text("", "", []),  # template fallback, see template_segments
            "casual_ar": Text(
                "المباراة خرجت عن السيطرة!",
                "9 كرات ضائعة في 5 دقائق فقط والإيقاع أصبح سريعاً جداً. كل شيء ممكن الآن.",
                ["9 كرات ضائعة في 5 دقائق.", "الإيقاع ارتفع من 14 إلى 23 حدثاً في الدقيقة."],
            ),
            "beginner_fr": Text(
                "Le match s'emballe",
                "Les deux équipes perdent souvent le ballon (9 pertes en 5 minutes) et le jeu va beaucoup "
                "plus vite. On dit que le match devient « chaotique ».",
                ["9 pertes de balle en 5 minutes.", "Le rythme est passé de 14 à 23 actions par minute."],
            ),
        },
        metric=(MetricName.CONTROL_CHAOS, "control_chaos_after", None),
        template_segments={"analyst_en"},
    ),
    Scripted(
        9,
        t2(86, 5),
        MomentKind.GOAL,
        HOME,
        ["H10"],
        1.0,
        {"xg": 0.12, "shot_speed_kmh": 117.4, "distance_to_goal_m": 18.6, "home_goals": 2, "away_goals": 1},
        "Goal for North City: Haddad scores. 2-1.",
        [
            (["m9_shot"], ["xg", "shot_speed_kmh", "distance_to_goal_m"]),
            (["m1_goal", "m6_goal", "m9_goal"], ["home_goals", "away_goals"]),
        ],
        {
            "analyst_en": Text(
                "Haddad's 0.12 xG winner",
                "Haddad scores from 18.6 m at 117.4 km/h, a chance worth only 0.12 xG. North City lead 2-1, "
                "completing the comeback from Halvorsen's early goal.",
                ["Haddad's shot: 0.12 xG from 18.6 m at 117.4 km/h.", "North City lead 2-1."],
            ),
            "casual_ar": Text(
                "Haddad يقلب الطاولة! 2-1",
                "صاروخ من Haddad بسرعة 117.4 كم/س من 18.6 متر! فرصة صعبة جداً بأهداف متوقعة 0.12 فقط، "
                "لكنه حوّلها إلى هدف. نورث سيتي يتقدم.",
                ["تسديدة Haddad: 117.4 كم/س من 18.6 متر.", "نورث سيتي يتقدم 2-1."],
            ),
            "beginner_fr": Text(
                "But exceptionnel de Haddad !",
                "Haddad marque de loin (18,6 m). Le xG du tir était de 0,12 : un tir très difficile, qui "
                "rentre rarement. North City mène 2-1.",
                ["Tir de Haddad : 0,12 xG depuis 18,6 m, à 117,4 km/h.", "North City mène 2-1."],
            ),
            "player_h10": Text(
                "Haddad wins it",
                "Rayan Haddad's 117.4 km/h strike from 18.6 m, a 0.12 xG chance, puts North City 2-1 up.",
                ["Haddad's shot: 0.12 xG from 18.6 m at 117.4 km/h.", "North City lead 2-1."],
            ),
        },
        insight_kind=InsightKind.COMMENTARY,
        priority=95,
        duration=9.0,
        metric=(MetricName.XG, "xg", None),
    ),
    Scripted(
        10,
        FT_T,
        MomentKind.PHASE,
        None,
        ["H9", "H10", "A9"],
        1.0,
        {
            "home_goals": 2,
            "away_goals": 1,
            "home_shots": 15,
            "away_shots": 8,
            "home_xg": 1.86,
            "away_xg": 0.97,
            "haddad_goals": 1,
            "haddad_assists": 1,
            "winner_xg": 0.12,
        },
        "Full-time: North City 2-1 Harbour United.",
        [
            (["m1_goal", "m6_goal", "m9_goal"], ["home_goals", "away_goals"]),
            (["ft"], ["home_shots", "away_shots", "home_xg", "away_xg"]),
            (["m6_pass", "m9_shot"], ["haddad_goals", "haddad_assists", "winner_xg"]),
        ],
        {
            "analyst_en": Text(
                "Full-time: North City 2-1 Harbour United",
                "North City came from behind with goals from Kaya (61') and Haddad (86'). They out-shot "
                "Harbour 15 to 8 and won the xG 1.86 to 0.97. Haddad was involved in both goals: 1 assist "
                "and 1 goal from a 0.12 xG chance.",
                ["Final score 2-1.", "Shots 15-8, xG 1.86-0.97.", "Haddad: 1 goal, 1 assist."],
            ),
            "casual_ar": Text(
                "نهاية المباراة: فوز نورث سيتي 2-1",
                "عودة رائعة! بعد التأخر بهدف مبكر، سجل Kaya وHaddad وقلبا النتيجة. فريقك سدد 15 مرة "
                "مقابل 8 وكان الأخطر هجومياً.",
                ["النتيجة النهائية 2-1.", "التسديدات 15 مقابل 8.", "Haddad: هدف وتمريرة حاسمة."],
            ),
            "beginner_fr": Text(
                "Fin du match : North City 2-1",
                "North City était mené 0-1 mais a gagné grâce aux buts de Kaya et Haddad. Il a tiré 15 fois "
                "contre 8 pour Harbour United : une victoire logique selon les statistiques.",
                [
                    "Score final : 2-1.",
                    "Tirs : 15 contre 8, xG : 1,86 contre 0,97.",
                    "Haddad : 1 but, 1 passe décisive.",
                ],
            ),
            "player_h10": Text(
                "Haddad's match: 1 goal, 1 assist",
                "Rayan Haddad decided the game: the assist for Kaya's equaliser and the winner from a 0.12 xG chance.",
                ["Final score 2-1.", "Shots 15-8, xG 1.86-0.97.", "Haddad: 1 goal, 1 assist."],
            ),
        },
        insight_kind=InsightKind.RECAP,
        slot=OverlaySlot.RECAP_CARD,
        priority=85,
        duration=20.0,
    ),
]
