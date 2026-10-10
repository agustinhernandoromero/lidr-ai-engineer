"""Escenarios de estrés: 3 perfiles de 10 turnos con hechos literales."""

from evals.stress.scenarios import SCENARIOS, facts_due


def test_three_profiles_of_ten_turns():
    assert set(SCENARIOS) == {"growing", "pivot", "contradiction"}
    for scenario in SCENARIOS.values():
        assert [t.index for t in scenario.turns] == list(range(1, 11))
        assert all(len(t.transcript) >= 20 for t in scenario.turns)


def test_every_fact_appears_literally_in_its_turn():
    for scenario in SCENARIOS.values():
        for turn in scenario.turns:
            if turn.fact:
                assert turn.fact.lower() in turn.transcript.lower(), (scenario.name, turn.index)


def test_project_name_is_the_first_fact():
    for scenario in SCENARIOS.values():
        assert scenario.turns[0].fact == scenario.project_name


def test_facts_due_are_those_declared_before_n():
    growing = SCENARIOS["growing"]
    assert facts_due(growing, 1) == []
    assert facts_due(growing, 3) == ["Nimbus", "autenticación"]


def test_profiles_force_pivot_and_contradiction():
    pivot = SCENARIOS["pivot"].turns
    assert "React" in pivot[0].transcript and pivot[4].fact == "Flutter"
    contradiction = SCENARIOS["contradiction"].turns
    assert contradiction[2].fact == "30.000" and contradiction[7].fact == "80.000"
