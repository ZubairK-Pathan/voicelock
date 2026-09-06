import streamlit as st
import tempfile
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

from predict import predict_speaker, verify_speaker, DEFAULT_THRESHOLD
from audio_utils import (
    load_embedding_model, load_profiles, get_device,
    register_speaker, delete_speaker,
)
from liveness import (
    generate_challenge, challenge_display, challenge_expected_words,
    run_liveness_check,
)

st.set_page_config(
    page_title="VoiceLock — Speaker Recognition",
    page_icon="🔐",
    layout="centered",
)

# ─── Global CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── Result cards ── */
.result-granted {
    background: linear-gradient(135deg, #0d1f12 0%, #0a2e18 100%);
    border: 1px solid #22c55e;
    border-left: 4px solid #22c55e;
    border-radius: 10px;
    padding: 20px 24px;
    margin: 16px 0;
}
.result-denied {
    background: linear-gradient(135deg, #1f0d0d 0%, #2e0a0a 100%);
    border: 1px solid #ef4444;
    border-left: 4px solid #ef4444;
    border-radius: 10px;
    padding: 20px 24px;
    margin: 16px 0;
}
.result-unknown {
    background: linear-gradient(135deg, #1a1400 0%, #2a2000 100%);
    border: 1px solid #f59e0b;
    border-left: 4px solid #f59e0b;
    border-radius: 10px;
    padding: 20px 24px;
    margin: 16px 0;
}
.result-title {
    font-size: 1.4rem;
    font-weight: 700;
    letter-spacing: 2px;
    margin: 0 0 6px 0;
}
.result-sub {
    font-size: 0.85rem;
    opacity: 0.7;
    margin: 0;
}
.granted-text { color: #22c55e; }
.denied-text  { color: #ef4444; }
.unknown-text { color: #f59e0b; }

/* ── Challenge digit display ── */
.challenge-box {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 28px 0;
    text-align: center;
    margin: 16px 0;
}
.challenge-digits {
    font-size: 3.5rem;
    font-weight: 700;
    letter-spacing: 24px;
    color: #60a5fa;
    font-variant-numeric: tabular-nums;
}
.challenge-label {
    font-size: 0.78rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 3px;
    margin-top: 8px;
}

/* ── Step badge ── */
.step-badge {
    display: inline-block;
    background: #1e293b;
    color: #94a3b8;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 3px 12px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 8px;
}
.step-complete {
    background: #0d2b1a;
    color: #22c55e;
    border-color: #22c55e;
}

/* ── Speaker pill in sidebar ── */
.speaker-pill {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
    margin-bottom: 6px;
    font-size: 0.85rem;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* ── Enrollment progress ── */
.enroll-step {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 10px;
    padding: 20px 24px;
    margin: 12px 0;
}
.enroll-step-done {
    border-color: #22c55e;
}

/* ── Metric row ── */
.metric-row {
    display: flex;
    gap: 16px;
    margin-top: 16px;
}
.metric-card {
    flex: 1;
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 14px 16px;
    text-align: center;
}
.metric-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: #e2e8f0;
}
.metric-label {
    font-size: 0.7rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 2px;
}
</style>
""", unsafe_allow_html=True)

REQUIRED_SAMPLES = 5


@st.cache_resource
def load_system():
    """Load model and profiles once; cached across all Streamlit reruns."""
    profiles = load_profiles()
    classifier = load_embedding_model()
    return profiles, classifier


def save_audio_bytes(audio_file, suffix=".wav") -> Path:
    """Persist a Streamlit audio buffer to a named temporary file and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(audio_file.getbuffer())
    tmp.close()
    return Path(tmp.name)


def cleanup(path: Path):
    """Delete a temporary file silently."""
    try:
        os.remove(path)
    except OSError:
        pass


def render_result_card(accepted: bool, speaker: str, score: float, threshold: float):
    """Render a styled ACCESS GRANTED / ACCESS DENIED result card."""
    if accepted:
        st.markdown(f"""
        <div class="result-granted">
            <p class="result-title granted-text">ACCESS GRANTED</p>
            <p class="result-sub">Identity verified as <strong>{speaker}</strong></p>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="result-denied">
            <p class="result-title denied-text">ACCESS DENIED</p>
            <p class="result-sub">Voice does not match <strong>{speaker}</strong></p>
        </div>""", unsafe_allow_html=True)

    st.markdown(f"""
    <div class="metric-row">
        <div class="metric-card">
            <div class="metric-value">{score:.3f}</div>
            <div class="metric-label">Similarity Score</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{threshold:.2f}</div>
            <div class="metric-label">Threshold</div>
        </div>
        <div class="metric-card">
            <div class="metric-value" style="color: {'#22c55e' if accepted else '#ef4444'};">
                {'✓ PASS' if accepted else '✗ FAIL'}
            </div>
            <div class="metric-label">Decision</div>
        </div>
    </div>""", unsafe_allow_html=True)


def render_unknown_card(best_match: str, score: float, threshold: float):
    """Render an UNKNOWN SPEAKER card."""
    st.markdown(f"""
    <div class="result-unknown">
        <p class="result-title unknown-text">UNKNOWN SPEAKER</p>
        <p class="result-sub">Closest match: <strong>{best_match}</strong> — score {score:.3f} below threshold {threshold:.2f}</p>
    </div>""", unsafe_allow_html=True)


def plot_scores(scores: dict, threshold: float):
    """Horizontal bar chart of cosine similarity scores."""
    sorted_scores = sorted(scores.items(), key=lambda x: x[1])
    speakers = [x[0] for x in sorted_scores]
    vals = [x[1] for x in sorted_scores]
    colors = ["#22c55e" if v >= threshold else "#334155" for v in vals]

    plt.rcParams.update({
        "figure.facecolor": "#0f172a",
        "axes.facecolor": "#0f172a",
        "axes.edgecolor": "#1e293b",
        "axes.labelcolor": "#94a3b8",
        "xtick.color": "#64748b",
        "ytick.color": "#e2e8f0",
        "text.color": "#e2e8f0",
        "grid.color": "#1e293b",
    })

    fig, ax = plt.subplots(figsize=(6, max(2.2, len(speakers) * 0.75)))
    bars = ax.barh(speakers, vals, color=colors, height=0.45, zorder=2)
    ax.axvline(threshold, color="#f59e0b", linestyle="--", linewidth=1.2,
               label=f"Threshold ({threshold:.2f})", zorder=3)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Cosine Similarity", fontsize=9)
    ax.set_title("Speaker Similarity Scores", fontsize=10, pad=10)
    ax.grid(axis="x", alpha=0.3, zorder=1)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.legend(fontsize=8, framealpha=0.2)
    for bar in bars:
        w = bar.get_width()
        ax.text(min(w + 0.02, 1.02), bar.get_y() + bar.get_height() / 2,
                f"{w:.3f}", va="center", fontsize=9, color="#e2e8f0")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    plt.rcdefaults()


# ─── Load System ─────────────────────────────────────────────────────────────

try:
    PROFILES, CLASSIFIER = load_system()
except Exception as e:
    st.error(f"**Could not load system:** {e}\n\nRun `python build_profiles.py` first.")
    st.stop()

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔐 VoiceLock")
    st.caption("Speaker Recognition System · Final Year CSE Project")
    st.divider()

    threshold = st.slider(
        "Acceptance Threshold",
        min_value=0.0, max_value=1.0,
        value=DEFAULT_THRESHOLD, step=0.05,
        help="Minimum cosine similarity to accept a speaker. Higher = stricter.",
    )
    st.divider()

    st.markdown("**Enrolled Speakers**")
    speakers_now = list(PROFILES.keys())
    if speakers_now:
        for sp in speakers_now:
            st.markdown(
                f'<div class="speaker-pill">👤 {sp}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No speakers enrolled yet.")

    st.divider()
    st.caption(f"Model: ECAPA-TDNN · 192-dim embeddings")
    st.caption(f"Liveness: Vosk digit challenge")

# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab_identify, tab_verify, tab_register, tab_manage = st.tabs([
    "Identify", "Verify", "Enroll", "Manage"
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — IDENTIFICATION
# ══════════════════════════════════════════════════════════════════════════════
with tab_identify:
    st.subheader("Speaker Identification")
    st.caption("Provide audio — the system determines who is speaking from all enrolled speakers.")

    if not PROFILES:
        st.warning("No speakers enrolled. Go to the **Enroll** tab first.")
    else:
        src = st.radio("", ["🎤 Record", "📂 Upload"], horizontal=True, key="id_src",
                       label_visibility="collapsed")
        audio_file = None
        if "Record" in src:
            audio_file = st.audio_input("Record a voice sample", key="id_mic")
        else:
            audio_file = st.file_uploader(
                "Audio file", type=["wav", "mp3", "m4a", "flac"], key="id_upload",
                label_visibility="collapsed"
            )

        if audio_file:
            st.audio(audio_file)
            if st.button("Run Identification", type="primary", key="id_btn"):
                with st.spinner("Analyzing voice..."):
                    tmp = save_audio_bytes(audio_file)
                    try:
                        result = predict_speaker(
                            audio_path=str(tmp),
                            threshold=threshold,
                            classifier=CLASSIFIER,
                            profiles=PROFILES,
                            verbose=False,
                        )
                        if result["is_unknown"]:
                            render_unknown_card(
                                result["predicted_speaker"],
                                result["similarity"],
                                threshold,
                            )
                        else:
                            st.markdown(f"""
                            <div class="result-granted">
                                <p class="result-title granted-text">{result['predicted_speaker'].upper()}</p>
                                <p class="result-sub">Identity established · Score: {result['similarity']:.3f}</p>
                            </div>""", unsafe_allow_html=True)

                        st.markdown("#### Similarity Breakdown")
                        plot_scores(result["all_scores"], threshold)
                    except Exception as e:
                        st.error(f"Error: {e}")
                    finally:
                        cleanup(tmp)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
with tab_verify:
    st.subheader("Speaker Verification")
    st.caption("Two-factor voice authentication: liveness check → identity verification.")

    if not PROFILES:
        st.warning("No speakers enrolled. Go to the **Enroll** tab first.")
    else:
        claimed = st.selectbox("Claiming identity as:", list(PROFILES.keys()), key="ver_name")

        # ── Liveness state ────────────────────────────────────────────────
        if "challenge" not in st.session_state or st.session_state.get("challenge_for") != claimed:
            st.session_state.challenge = generate_challenge(3)
            st.session_state.challenge_for = claimed
            st.session_state.liveness_passed = False

        challenge = st.session_state.challenge
        liveness_done = st.session_state.get("liveness_passed", False)

        # ── Step 1 ────────────────────────────────────────────────────────
        badge_class = "step-badge step-complete" if liveness_done else "step-badge"
        badge_text = "STEP 1 · COMPLETE" if liveness_done else "STEP 1 · LIVENESS CHECK"
        st.markdown(f'<span class="{badge_class}">{badge_text}</span>', unsafe_allow_html=True)

        if not liveness_done:
            st.markdown("Speak the digits displayed below to confirm you are physically present.")
            st.markdown(f"""
            <div class="challenge-box">
                <div class="challenge-digits">{challenge_display(challenge)}</div>
                <div class="challenge-label">Say these digits aloud</div>
            </div>""", unsafe_allow_html=True)
            st.caption(f"Spoken form: *{' · '.join(challenge_expected_words(challenge))}*")

            liveness_audio = st.audio_input("Record the digits", key="liveness_mic")

            col_btn, col_new = st.columns([2, 1])
            if liveness_audio:
                if col_btn.button("Submit", type="primary", key="liveness_btn"):
                    with st.spinner("Verifying..."):
                        tmp = save_audio_bytes(liveness_audio)
                        try:
                            is_live, reason, transcript = run_liveness_check(str(tmp), challenge)
                            if is_live:
                                st.session_state.liveness_passed = True
                                st.toast(f"Liveness confirmed — heard: {transcript}", icon="✅")
                                st.rerun()
                            else:
                                st.markdown(f"""
                                <div class="result-denied">
                                    <p class="result-title denied-text" style="font-size:1rem;">LIVENESS FAILED</p>
                                    <p class="result-sub">{reason}</p>
                                </div>""", unsafe_allow_html=True)
                        finally:
                            cleanup(tmp)

            if col_new.button("New digits", key="new_challenge"):
                st.session_state.challenge = generate_challenge(3)
                st.session_state.liveness_passed = False
                st.rerun()
        else:
            st.markdown(f"""
            <div style="background:#0d1f12;border:1px solid #22c55e;border-radius:8px;
                        padding:12px 16px;margin:8px 0;font-size:0.85rem;color:#22c55e;">
                ✓ &nbsp;Liveness confirmed
            </div>""", unsafe_allow_html=True)

        # ── Step 2 ────────────────────────────────────────────────────────
        st.markdown("")
        badge2_class = "step-badge"
        st.markdown(f'<span class="{badge2_class}">STEP 2 · IDENTITY VERIFICATION</span>',
                    unsafe_allow_html=True)

        if liveness_done:
            st.markdown("Now provide your voice for speaker matching.")
            src = st.radio("", ["🎤 Record", "📂 Upload"], horizontal=True, key="ver_src",
                           label_visibility="collapsed")
            audio_file = None
            if "Record" in src:
                audio_file = st.audio_input("Record your voice", key="ver_mic")
            else:
                audio_file = st.file_uploader(
                    "Audio file", type=["wav", "mp3", "m4a", "flac"], key="ver_upload",
                    label_visibility="collapsed"
                )

            if audio_file:
                st.audio(audio_file)
                if st.button(f"Verify as {claimed}", type="primary", key="ver_btn"):
                    with st.spinner("Verifying identity..."):
                        tmp = save_audio_bytes(audio_file)
                        try:
                            result = verify_speaker(
                                audio_path=str(tmp),
                                claimed_identity=claimed,
                                threshold=threshold,
                                classifier=CLASSIFIER,
                                profiles=PROFILES,
                                verbose=False,
                            )
                            render_result_card(
                                result["is_accepted"], claimed,
                                result["similarity"], threshold
                            )
                            st.session_state.liveness_passed = False
                            st.session_state.challenge = generate_challenge(3)
                        except Exception as e:
                            st.error(f"Error: {e}")
                        finally:
                            cleanup(tmp)
        else:
            st.markdown(
                '<p style="color:#475569;font-size:0.85rem;margin-top:8px;">'
                'Complete Step 1 to unlock identity verification.</p>',
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ENROLLMENT
# ══════════════════════════════════════════════════════════════════════════════
with tab_register:
    st.subheader("Enroll New Speaker")
    st.caption(
        f"Record {REQUIRED_SAMPLES} voice samples (~5 seconds each). "
        "The system averages their embeddings into a biometric voiceprint."
    )

    if "reg_samples" not in st.session_state:
        st.session_state.reg_samples = []
    if "reg_done" not in st.session_state:
        st.session_state.reg_done = False

    name_input = st.text_input("Full name:", placeholder="e.g. Zubair", key="reg_name")

    if name_input:
        if name_input.strip() in PROFILES:
            st.warning(f"**{name_input.strip()}** is already enrolled.")
        else:
            collected = len(st.session_state.reg_samples)

            # Progress bar
            progress_pct = collected / REQUIRED_SAMPLES
            st.progress(progress_pct)
            st.caption(f"{collected} of {REQUIRED_SAMPLES} samples recorded")

            if collected < REQUIRED_SAMPLES:
                st.markdown(f"""
                <div class="enroll-step">
                    <div style="font-size:0.75rem;color:#64748b;text-transform:uppercase;
                                letter-spacing:1.5px;margin-bottom:8px;">
                        Sample {collected + 1} of {REQUIRED_SAMPLES}
                    </div>
                    <div style="color:#e2e8f0;font-size:0.9rem;">
                        Speak any full sentence clearly. Vary your sentences across samples.
                    </div>
                </div>""", unsafe_allow_html=True)

                sample_audio = st.audio_input(
                    f"Record sample {collected + 1}", key=f"reg_sample_{collected}"
                )
                if sample_audio:
                    if st.button(f"Accept sample {collected + 1}", key=f"reg_accept_{collected}"):
                        tmp_path = save_audio_bytes(sample_audio)
                        st.session_state.reg_samples.append(str(tmp_path))
                        st.rerun()

            if collected >= REQUIRED_SAMPLES and not st.session_state.reg_done:
                st.markdown(f"""
                <div class="result-granted" style="margin-top:16px;">
                    <p class="result-title granted-text" style="font-size:1rem;">
                        All samples collected
                    </p>
                    <p class="result-sub">Ready to generate voiceprint for {name_input.strip()}</p>
                </div>""", unsafe_allow_html=True)

                if st.button("Generate Voiceprint", type="primary", key="reg_submit"):
                    with st.spinner("Computing embeddings and building profile..."):
                        try:
                            updated = register_speaker(
                                name=name_input.strip(),
                                audio_paths=[Path(p) for p in st.session_state.reg_samples],
                                classifier=CLASSIFIER,
                                existing_profiles=PROFILES,
                            )
                            PROFILES.update(updated)
                            st.session_state.reg_done = True
                            st.session_state.reg_samples = []
                            st.markdown(f"""
                            <div class="result-granted">
                                <p class="result-title granted-text">ENROLLED</p>
                                <p class="result-sub">
                                    {name_input.strip()} is now registered and available for
                                    identification and verification.
                                </p>
                            </div>""", unsafe_allow_html=True)
                        except Exception as e:
                            st.error(f"Enrollment failed: {e}")

            col1, _ = st.columns([1, 3])
            if col1.button("Start over", key="reg_reset"):
                for p in st.session_state.reg_samples:
                    cleanup(Path(p))
                st.session_state.reg_samples = []
                st.session_state.reg_done = False
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — MANAGE
# ══════════════════════════════════════════════════════════════════════════════
with tab_manage:
    st.subheader("Manage Enrolled Speakers")
    st.caption("Remove a speaker from the recognition system. Their audio files are preserved on disk.")

    if not PROFILES:
        st.info("No speakers enrolled yet.")
    else:
        for sp in list(PROFILES.keys()):
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"""
                <div class="speaker-pill" style="border-radius:8px;padding:12px 16px;">
                    <span style="font-size:1.1rem;">👤</span>
                    <div>
                        <div style="font-weight:600;color:#e2e8f0;">{sp}</div>
                        <div style="font-size:0.72rem;color:#64748b;">192-dimensional ECAPA-TDNN voiceprint</div>
                    </div>
                </div>""", unsafe_allow_html=True)
            with col2:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                if st.button("Remove", key=f"del_{sp}"):
                    try:
                        delete_speaker(sp, PROFILES)
                        st.toast(f"{sp} removed from the system.", icon="🗑️")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
