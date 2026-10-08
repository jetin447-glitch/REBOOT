"""
REBOOT - Your Personal Rhythm
A simple daily-rhythm tracker for students, built with Streamlit.

Run with:  streamlit run reboot_app.py

How the file is organised (top to bottom):
  1. Setup          - page settings and the (very small) CSS style
  2. Health data    - a small, modular "provider" system for steps and sleep
  3. Score logic    - the functions that turn your day into a score
  4. Session state  - where results are kept while the app is open
  5. Callbacks      - what happens when a button is clicked
  6. Interface      - the header and the three tabs (Home, Check-In, Progress)

Note: the score is a simple self-reflection tool. It is NOT medical advice
and it does not diagnose anything.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# 1. SETUP
# ---------------------------------------------------------------------------

st.set_page_config(page_title="REBOOT", page_icon="🔄", layout="centered")

# Minimal styling. Colours use transparency, so they work in light AND dark mode.
# Sizes use rem / clamp() / vw instead of fixed pixels so the layout scales on
# phones, tablets and laptops.
st.markdown(
    """
    <style>
    /* Page spacing. The top padding is large enough to clear Streamlit's own
       header bar, so the title is never covered or cut off. */
    .block-container { padding: 4.5rem 1rem 3rem 1rem; max-width: 720px; }
    html, body { max-width: 100%; overflow-x: hidden; }

    /* Logo: a tiny power symbol + the word REBOOT.
       clamp(min, preferred, max) lets the size grow and shrink with the screen. */
    .brand { display: flex; align-items: center; gap: 0.6rem; }
    .brand svg {
        width: clamp(1.4rem, 6vw, 2rem);
        height: clamp(1.4rem, 6vw, 2rem);
        flex-shrink: 0;
    }
    .brand-name {
        font-size: clamp(1.6rem, 8vw, 2.6rem);
        font-weight: 700;
        letter-spacing: 0.08em;
        line-height: 1.3;
        white-space: nowrap;
    }
    .app-subtitle { opacity: 0.6; margin: 0 0 1.5rem 0; }

    /* Score card */
    .card {
        background: rgba(128, 128, 128, 0.10);
        border-radius: 20px;
        padding: 1.75rem 1rem;
        text-align: center;
        margin-bottom: 1rem;
    }
    .card-label { opacity: 0.65; font-size: 0.95rem; }
    .card-score { font-size: clamp(3.5rem, 18vw, 5.5rem); font-weight: 700; line-height: 1.1; }
    .card-of    { opacity: 0.5; font-size: 0.9rem; }

    /* Touch-friendly controls: tall buttons, tall inputs, 16px text
       (16px also stops iPhones from zooming in when you tap an input). */
    .stButton > button, [data-testid="stFormSubmitButton"] > button {
        min-height: 3rem;
        width: 100%;
        border-radius: 12px;
        transition: transform 0.12s ease;   /* the tiny "bloop" */
    }
    .stButton > button:active, [data-testid="stFormSubmitButton"] > button:active {
        transform: scale(0.96);
    }
    [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input { min-height: 2.75rem; font-size: 1rem; }
    button[data-baseweb="tab"] { min-height: 3rem; }

    /* Rounded bordered containers */
    [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 16px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 2. HEALTH DATA (modular)
# ---------------------------------------------------------------------------
# IMPORTANT: a normal web page (and therefore Streamlit) CANNOT read Apple
# Health or Google Health Connect. Browsers do not offer any standard way to
# access steps or sleep data. Only a native Android/iOS app can ask the phone's
# operating system for that data (with the user's permission).
#
# So this section is built as a set of "providers". Each provider knows how to
# fetch health data from ONE source. The rest of the app only calls
# load_health_data() and does not care where the numbers came from.
#
#   Today:   AppWrapperProvider  -> reads values handed over by a native app
#            (nothing available in a normal browser -> manual entry is used)
#   Future:  add a new class (for example for Android Health Connect or Apple
#            HealthKit), put it in PROVIDERS, and nothing else has to change.


@dataclass
class HealthSample:
    """The health values a provider can return. None means 'not available'."""

    steps: Optional[int] = None
    sleep_hours: Optional[float] = None
    source: str = ""


class HealthProvider:
    """Base class. Every provider has the same two methods."""

    name = "unknown source"

    def is_available(self) -> bool:
        """Can this provider supply data right now?"""
        return False

    def fetch(self) -> Optional[HealthSample]:
        """Return a HealthSample, or None if nothing could be read."""
        return None


class AppWrapperProvider(HealthProvider):
    """
    Reads steps and sleep from the page address, e.g.
        http://localhost:8501/?steps=6400&sleep=7.5
    A future Android/iOS app that shows REBOOT inside a WebView could ask the
    user for health permission natively, then open REBOOT with these values.
    In a normal browser the address has no such values, so this provider
    reports itself as unavailable.
    """

    name = "your app"

    @staticmethod
    def _read_number(key):
        raw = st.query_params.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def is_available(self) -> bool:
        return self._read_number("steps") is not None or self._read_number("sleep") is not None

    def fetch(self) -> Optional[HealthSample]:
        steps = self._read_number("steps")
        sleep = self._read_number("sleep")
        if steps is None and sleep is None:
            return None
        return HealthSample(
            steps=None if steps is None else int(max(0, min(steps, 100000))),
            sleep_hours=None if sleep is None else max(0.0, min(sleep, 16.0)),
            source=self.name,
        )


# Providers are tried in this order. Add future ones here.
PROVIDERS = [AppWrapperProvider()]


def load_health_data():
    """Try each provider and return the first sample that has data (or None)."""
    for provider in PROVIDERS:
        if provider.is_available():
            sample = provider.fetch()
            if sample is not None:
                return sample
    return None


# ---------------------------------------------------------------------------
# 3. SCORE LOGIC
# ---------------------------------------------------------------------------
# Each area is worth some points. Together the weights add up to 100.
# "tip" is the single recommendation shown if that area is the weakest.

AREAS = {
    "sleep": {
        "label": "Sleep",
        "weight": 25,
        "tip": "Try getting to bed a little earlier tonight.",
    },
    "study": {
        "label": "Study",
        "weight": 15,
        "tip": "Set aside one focused study session tomorrow.",
    },
    "exercise": {
        "label": "Exercise",
        "weight": 15,
        "tip": "Add a short period of physical activity tomorrow.",
    },
    "screen": {
        "label": "Screen time",
        "weight": 15,
        "tip": "Try taking a few screen-free breaks.",
    },
    "mood": {
        "label": "Mood",
        "weight": 15,
        "tip": "Do one small thing you enjoy, or chat with someone you trust.",
    },
    "energy": {
        "label": "Energy",
        "weight": 15,
        "tip": "Drink some water, get a bit of daylight and stretch for a few minutes.",
    },
}


def clamp(value):
    """Keep a number between 0 and 1."""
    return max(0.0, min(1.0, value))


def area_fractions(sleep, study, exercise, steps, screen, mood, energy):
    """
    Turn each answer into a fraction from 0.0 (poor) to 1.0 (great).
    """
    # Sleep: 7-9 hours is the full target. Less or much more lowers the fraction.
    if sleep < 7:
        sleep_f = sleep / 7
    elif sleep <= 9:
        sleep_f = 1.0
    else:
        sleep_f = 1 - (sleep - 9) / 4

    # Exercise: 30 active minutes OR 8000 steps reaches the full target.
    # We take whichever of the two is better.
    exercise_f = max(exercise / 30, steps / 8000)

    return {
        "sleep": clamp(sleep_f),
        # Study: 2 hours reaches the full target.
        "study": clamp(study / 2),
        "exercise": clamp(exercise_f),
        # Screen time: up to 3 hours is fine, then it drops to 0 at 10 hours.
        "screen": clamp(1 - (screen - 3) / 7),
        # Mood and energy are rated 1-5.
        "mood": clamp(mood / 5),
        "energy": clamp(energy / 5),
    }


def calculate_score(fractions):
    """Multiply each fraction by its weight and add them up (0-100)."""
    total = sum(fractions[key] * AREAS[key]["weight"] for key in AREAS)
    return round(total)


def find_weakest(fractions):
    """The weakest area is the one with the lowest fraction."""
    return min(fractions, key=fractions.get)


def score_message(score):
    """A short message that matches the score."""
    if score >= 85:
        return "Great rhythm today. Keep it going."
    if score >= 70:
        return "A solid day. A small tweak could make it even better."
    if score >= 50:
        return "A decent day. There is room to improve."
    return "A tough day happens to everyone. Start small tomorrow."


# ---------------------------------------------------------------------------
# 4. SESSION STATE
# ---------------------------------------------------------------------------
# Streamlit re-runs this whole file after every click. st.session_state is
# a dictionary that survives those re-runs, so we keep our results there.

if "history" not in st.session_state:
    st.session_state.history = []  # one dictionary per saved day

# Starting values for the Check-In form. Keeping them in session state means
# the "Connect Health Data" button can fill them in for the user.
FORM_DEFAULTS = {
    "in_date": date.today(),
    "in_sleep": 7.0,
    "in_study": 2.0,
    "in_exercise": 30,
    "in_steps": 0,
    "in_screen": 4.0,
    "in_mood": 3,
    "in_energy": 3,
}
for key, value in FORM_DEFAULTS.items():
    st.session_state.setdefault(key, value)


# ---------------------------------------------------------------------------
# 5. CALLBACKS (run when a button is clicked)
# ---------------------------------------------------------------------------

def connect_health():
    """Ask the health providers for data and fill in the form if we get any."""
    sample = load_health_data()
    if sample is None:
        st.session_state.health_status = ("unavailable", "")
        return

    if sample.sleep_hours is not None:
        st.session_state.in_sleep = round(sample.sleep_hours * 2) / 2  # nearest 0.5
    if sample.steps is not None:
        st.session_state.in_steps = sample.steps
    st.session_state.health_status = ("connected", sample.source)


def save_checkin():
    """Read the form values, calculate the score and store the result."""
    state = st.session_state
    fractions = area_fractions(
        state.in_sleep,
        state.in_study,
        state.in_exercise,
        state.in_steps,
        state.in_screen,
        state.in_mood,
        state.in_energy,
    )
    entry = {
        "date": state.in_date,
        "score": calculate_score(fractions),
        "fractions": fractions,
        "weakest": find_weakest(fractions),
    }

    # One result per day: replace an older entry for the same date.
    state.history = [e for e in state.history if e["date"] != entry["date"]]
    state.history.append(entry)
    state.history.sort(key=lambda e: e["date"])
    state.just_saved = True


def reset_data():
    """Clear everything stored in this session."""
    st.session_state.history = []
    st.session_state.pop("health_status", None)


# ---------------------------------------------------------------------------
# 6. INTERFACE
# ---------------------------------------------------------------------------

# Logo: a simple power symbol (drawn with SVG) next to the word REBOOT.
st.markdown(
    """
    <div class="brand">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 3v8"/>
            <path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>
        </svg>
        <span class="brand-name">REBOOT</span>
    </div>
    <p class="app-subtitle">Your Personal Rhythm</p>
    """,
    unsafe_allow_html=True,
)

tab_home, tab_checkin, tab_progress = st.tabs(["Home", "Check-In", "Progress"])

# ---------- HOME ----------
with tab_home:
    today_entries = [e for e in st.session_state.history if e["date"] == date.today()]

    if not today_entries:
        st.markdown(
            """
            <div class="card">
                <div class="card-label">Today's Reboot Score</div>
                <div class="card-score">--</div>
                <div class="card-of">No check-in yet</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("Open the **Check-In** tab to log your day.")
    else:
        today = today_entries[0]
        weakest = today["weakest"]

        st.markdown(
            f"""
            <div class="card">
                <div class="card-label">Today's Reboot Score</div>
                <div class="card-score">{today['score']}</div>
                <div class="card-of">out of 100</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write(score_message(today["score"]))

        with st.container(border=True):
            st.caption("Weakest area")
            st.subheader(AREAS[weakest]["label"])

        with st.container(border=True):
            st.caption("Recommendation")
            if today["fractions"][weakest] >= 0.9:
                st.write("Your day looks well balanced. Keep doing what you are doing.")
            else:
                st.write(AREAS[weakest]["tip"])

        with st.expander("How was this score calculated?"):
            st.write(
                "Each area is turned into a value between 0 and 1, then multiplied "
                "by its weight. The points add up to a maximum of 100. "
                "For exercise, 30 active minutes or 8000 steps both count as full marks."
            )
            rows = []
            for key, info in AREAS.items():
                points = today["fractions"][key] * info["weight"]
                rows.append(
                    {
                        "Area": info["label"],
                        "Points": f"{points:.1f} / {info['weight']}",
                    }
                )
            st.table(pd.DataFrame(rows).set_index("Area"))

    st.caption(
        "REBOOT is a self-reflection tool, not medical advice. "
        "The score is a simple estimate and does not diagnose anything."
    )

# ---------- CHECK-IN ----------
with tab_checkin:
    st.subheader("Daily Check-In")

    if st.session_state.pop("just_saved", False):
        st.success("Saved. Open the Home tab to see your score.")

    # --- Health data (optional) ---
    with st.container(border=True):
        st.markdown("**Health data**")
        st.caption(
            "Optional. REBOOT only uses steps and sleep if your device or app "
            "shares them with your permission."
        )
        st.button("Connect Health Data", on_click=connect_health)

        status = st.session_state.get("health_status")
        if status is not None:
            kind, source = status
            if kind == "connected":
                st.success(f"Steps and sleep loaded from {source}. Check them below, then save.")
            else:
                st.info(
                    "Automatic access isn't available here. Web browsers cannot read "
                    "Apple Health or Google Health Connect, so please enter your "
                    "sleep and steps manually below."
                )

    # --- The check-in form ---
    with st.form("checkin_form"):
        st.date_input("Date", max_value=date.today(), key="in_date")

        col1, col2 = st.columns(2)  # columns stack automatically on phones
        with col1:
            st.number_input("Sleep (hours)", 0.0, 16.0, step=0.5, key="in_sleep")
            st.number_input("Exercise (minutes)", 0, 300, step=5, key="in_exercise")
            st.number_input("Screen time (hours)", 0.0, 18.0, step=0.5, key="in_screen")
        with col2:
            st.number_input("Study time (hours)", 0.0, 16.0, step=0.5, key="in_study")
            st.number_input("Steps (optional)", 0, 100000, step=500, key="in_steps")

        st.slider("Mood (1 = low, 5 = great)", 1, 5, key="in_mood")
        st.slider("Energy (1 = low, 5 = high)", 1, 5, key="in_energy")

        st.form_submit_button("Save check-in", on_click=save_checkin)

# ---------- PROGRESS ----------
with tab_progress:
    st.subheader("Progress")
    history = st.session_state.history

    if not history:
        st.write("No results yet. Save a check-in to see your progress.")
    else:
        scores = [e["score"] for e in history]

        col1, col2, col3 = st.columns(3)
        col1.metric("Average", f"{sum(scores) / len(scores):.0f}")
        col2.metric("Best", max(scores))
        col3.metric("Check-ins", len(scores))

        table = pd.DataFrame(
            {
                "Date": [e["date"].strftime("%d %b %Y") for e in history],
                "Score": scores,
                "Weakest area": [AREAS[e["weakest"]]["label"] for e in history],
            }
        )

        st.caption("Score over time")
        chart_data = pd.DataFrame(
            {"Score": scores},
            index=pd.to_datetime([e["date"] for e in history]),  # real dates keep the order correct
        )
        st.line_chart(chart_data)

        st.caption("Previous scores (newest first)")
        st.table(table.iloc[::-1].set_index("Date"))

# ---------- RESET ----------
st.divider()
st.button("Reset session data", on_click=reset_data)