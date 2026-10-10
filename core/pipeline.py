"""One shared, resumable pipeline for recordings and imported files."""
from __future__ import annotations
import logging
import time
from config.localization import tr
from core.audio import Segment, audio_windows, merge_segments, repetition_loop, wav_duration
from core.corrections import apply_corrections, protect_names, restore_names
from core.live_text import extract_enter_command
from core.models import Cancelled
from core.session import AudioJob, ResultVersion
from core.text_optimizer import TextOptimizationOptions

LOGGER = logging.getLogger("winwhisperplus")


def options_from_settings(settings, target=None):
    enabled = settings.text_optimization_enabled
    return TextOptimizationOptions(
        formatting=enabled and settings.text_optimization_formatting_enabled,
        cleanup=enabled and settings.text_optimization_cleanup_enabled,
        redact=enabled and settings.text_optimization_redact_enabled,
        translation_target=target,
    )


def run_job(job: AudioJob, version: ResultVersion, settings, transcriber, optimizer, progress=lambda value: None):
    """Mutates only this job/version. Successful section results survive retries."""
    rules = settings.correction_rules if settings.correction_rules_enabled else []
    should_enter = False
    try:
        job.duration = wav_duration(job.audio_path)
        language = version.language
        segments = []
        failed = False
        for index, (start, samples) in enumerate(audio_windows(job.audio_path)):
            if job.cancel.is_set():
                raise Cancelled("Cancelled")
            before = time.monotonic()
            section = version.sections.get(index)
            if section is None or section.get("error"):
                try:
                    local, detected = transcriber.transcribe_segments(samples, language, cancel=job.cancel)
                    if language is None and detected:
                        language = detected
                    if repetition_loop("".join(s.text for s in local)):
                        local, _ = transcriber.transcribe_segments(samples, language, cancel=job.cancel, no_context=True)
                        warning = f"Repetition detected at {start:.1f}s; section retried without context"
                        if warning not in version.warnings:
                            version.warnings.append(warning)
                        if repetition_loop("".join(s.text for s in local)):
                            raise RuntimeError("Persistent repetition loop; retry this section with a different model")
                    section = {"segments": [Segment(s.start + start, s.end + start, s.text) for s in local], "error": ""}
                except Cancelled:
                    raise
                except Exception as exc:
                    section = {"segments": [], "error": str(exc)}
                    LOGGER.exception("Job %s section %s failed", job.id, index)
                version.sections[index] = section
            failed |= bool(section["error"])
            segments = merge_segments(segments, section["segments"], start)
            version.raw_text = "".join(s.text for s in segments).strip()
            version.language = language
            LOGGER.info("Job %s section %s start=%.2f duration=%.2f runtime=%.2f model=%s error=%s",
                        job.id, index, start, len(samples) / 16000, time.monotonic() - before, version.model, bool(section["error"]))
            job.progress = min(0.85, (start + len(samples) / 16000) / max(job.duration, 0.01) * 0.85)
            progress(job.progress)
        version.language = language
        version.raw_text = "".join(segment.text for segment in segments).strip()
        source = version.raw_text
        if job.source == "microphone":
            source, should_enter = extract_enter_command(source)
        version.corrected_text = apply_corrections(source, rules)
        version.text = version.corrected_text if not version.target else ""
        if failed:
            version.status = "failed"
            version.error = "\n".join(f"Section {i + 1}: {s['error']}" for i, s in version.sections.items() if s["error"])
            return False
        if job.cancel.is_set():
            raise Cancelled("Cancelled")
        options = options_from_settings(settings, version.target)
        if version.corrected_text and options.has_work(language):
            protected, names = protect_names(version.corrected_text, rules)
            try:
                if hasattr(optimizer, "prepare"):
                    last_percent = [-1]
                    def model_progress(current, total):
                        percent = int(current / total * 100)
                        if percent == last_percent[0]:
                            return
                        last_percent[0] = percent
                        job.phase = tr("text_model_preparing", settings, percent=percent)
                        progress(job.progress)
                    job.phase = tr("text_model_loading", settings)
                    progress(job.progress)
                    optimizer.prepare(cancel=job.cancel, progress=model_progress)
                job.phase = tr("text_model_processing", settings)
                progress(job.progress)
                output = optimizer.optimize(protected, options=options, language=language, cancel=job.cancel)
                version.text = restore_names(output, names)
            except Cancelled:
                raise
            except Exception as exc:
                version.status = "translation_failed" if version.target else "optimization_failed"
                version.error = str(exc)
                return False if version.target else should_enter
        elif version.target:
            version.text = version.corrected_text  # same source/target language
        version.status = "complete"
        version.error = ""
        job.progress = 1.0
        progress(1.0)
        return should_enter
    except Cancelled:
        version.status = "cancelled"
        version.error = "cancelled"
        return False
    except Exception as exc:
        version.status = "failed"
        version.error = str(exc)
        LOGGER.exception("Job %s failed", job.id)
        return False
