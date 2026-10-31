"""Assemble shots into scene files and an episode file, rebuilding only what changed."""
import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from app.media import ops
from app.media.runner import Profile, default_profile

log = logging.getLogger("media.assemble")


@dataclass
class BuiltFile:
    key: str
    path: str
    duration: float
    cached: bool


@dataclass
class EpisodeResult:
    episode: BuiltFile
    scenes: list[dict] = field(default_factory=list)  # {scene_id, key, path, duration, cached, shot_ids}
    shots: list[dict] = field(default_factory=list)   # {shot_id, scene_id, key, path, duration, cached, start}
    subtitle_srt: str | None = None
    rebuilt_shots: int = 0
    rebuilt_scenes: int = 0


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _build(target: Path, builder) -> bool:
    """Run `builder(partial_path)` unless `target` exists; returns True if it was built."""
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial" + target.suffix)
    try:
        builder(partial)
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()
    return True


def shot_key(shot: dict, profile: Profile) -> str:
    return _digest({
        "clip": file_hash(shot["clip"]), "trim": shot.get("trim_seconds"), "hold": bool(shot.get("hold_last_frame")),
        "tracks": [{"file": file_hash(t["path"]), "start": t.get("start_seconds", 0), "gain": t.get("gain", 1),
                    "role": t.get("role", "sfx")} for t in shot.get("audio_tracks", [])],
        "keep_original_audio": shot.get("keep_original_audio", True), "profile": profile.key(),
    })


def assemble_episode(shots: Sequence[dict], workdir: str | Path, profile: Profile | None = None,
                     crossfade: float = 0.0, subtitle_mode: str | None = "soft",
                     episode_name: str = "episode") -> EpisodeResult:
    """Build scene files and the episode file from ordered shots.

    Each shot: {shot_id, scene_id, clip, trim_seconds, audio_tracks=[{path, start_seconds, gain, role}],
    subtitles=[{start, end, text}] (seconds relative to the shot), hold_last_frame=False}. Shots of one scene must
    be adjacent. Intermediate files are keyed by a content hash, so a changed shot rebuilds only its scene and the
    episode; everything else is reused from `workdir`. `crossfade` applies between shots inside a scene.
    `subtitle_mode` is "soft", "burn" or None.
    """
    profile = profile or default_profile()
    work = Path(workdir)
    result = EpisodeResult(episode=BuiltFile("", "", 0.0, False))

    built: list[tuple[dict, str, Path, float]] = []
    for index, shot in enumerate(shots):
        key = shot_key(shot, profile)
        target = work / "shots" / f"{key}.mp4"

        def build_shot(partial: Path, shot=shot, key=key):
            scratch = work / "tmp" / key
            scratch.mkdir(parents=True, exist_ok=True)
            normalized = scratch / "normalized.mp4"
            ops.normalize(shot["clip"], normalized, profile)
            seconds = shot.get("trim_seconds")
            trimmed = scratch / "trimmed.mp4"
            if seconds:
                ops.trim(normalized, trimmed, float(seconds), hold_last_frame=bool(shot.get("hold_last_frame")),
                         profile=profile)
            else:
                trimmed = normalized
            tracks = shot.get("audio_tracks") or []
            if tracks:
                ops.mix_audio(trimmed, tracks, partial, keep_original_audio=shot.get("keep_original_audio", True),
                              profile=profile)
            else:
                shutil.copyfile(trimmed, partial)
            for leftover in scratch.glob("*"):
                leftover.unlink()
            scratch.rmdir()

        fresh = _build(target, build_shot)
        duration = ops.probe(target).duration
        result.rebuilt_shots += int(fresh)
        built.append((shot, key, target, duration))
        result.shots.append({"shot_id": shot.get("shot_id", index), "scene_id": shot["scene_id"], "key": key,
                             "path": str(target), "duration": duration, "cached": not fresh, "start": 0.0})

    # Group adjacent shots by scene.
    scenes: list[list[int]] = []
    for position, (shot, *_rest) in enumerate(built):
        if scenes and built[scenes[-1][-1]][0]["scene_id"] == shot["scene_id"]:
            scenes[-1].append(position)
        else:
            scenes.append([position])

    scene_paths: list[Path] = []
    segments: list[dict] = []
    episode_cursor = 0.0
    for members in scenes:
        scene_id = built[members[0]][0]["scene_id"]
        scene_key = _digest({"shots": [built[m][1] for m in members], "crossfade": crossfade, "profile": profile.key()})
        target = work / "scenes" / f"{scene_key}.mp4"
        clips = [built[m][2] for m in members]
        fresh = _build(target, lambda partial, clips=clips: ops.concat(clips, partial, crossfade=crossfade,
                                                                       profile=profile))
        scene_duration = ops.probe(target).duration
        result.rebuilt_scenes += int(fresh)
        cursor = episode_cursor
        for j, m in enumerate(members):
            shot, _key, _path, duration = built[m]
            result.shots[m]["start"] = round(cursor, 3)
            for seg in shot.get("subtitles") or []:
                segments.append({"start": cursor + float(seg["start"]), "end": cursor + float(seg["end"]),
                                 "text": seg["text"]})
            cursor += duration - (crossfade if j < len(members) - 1 else 0.0)
        result.scenes.append({"scene_id": scene_id, "key": scene_key, "path": str(target), "duration": scene_duration,
                              "cached": not fresh, "shot_ids": [result.shots[m]["shot_id"] for m in members]})
        scene_paths.append(target)
        episode_cursor += scene_duration

    episode_key = _digest({"scenes": [s["key"] for s in result.scenes], "subs": segments,
                           "mode": subtitle_mode if segments else None})
    episode_path = work / "episodes" / f"{episode_name}-{episode_key}.mp4"

    def build_episode(partial: Path):
        if len(scene_paths) == 1 and not (segments and subtitle_mode):
            partial.write_bytes(scene_paths[0].read_bytes())
            return
        joined = work / "tmp" / f"{episode_key}-joined.mp4"
        joined.parent.mkdir(parents=True, exist_ok=True)
        try:
            ops.concat(scene_paths, joined, crossfade=0.0, profile=profile)
            if segments and subtitle_mode:
                ops.add_subtitles(joined, segments, partial, mode=subtitle_mode, profile=profile)
            else:
                os.replace(joined, partial)
        finally:
            if joined.exists():
                joined.unlink()

    fresh = _build(episode_path, build_episode)
    if segments:
        srt_path = work / "episodes" / f"{episode_name}-{episode_key}.srt"
        srt_path.write_text(ops.to_srt(segments), encoding="utf-8")
        result.subtitle_srt = str(srt_path)
    result.episode = BuiltFile(episode_key, str(episode_path), ops.probe(episode_path).duration, not fresh)
    log.info("Assembled %s: %d shots (%d rebuilt), %d scenes (%d rebuilt)", episode_name, len(built),
             result.rebuilt_shots, len(scenes), result.rebuilt_scenes)
    return result
