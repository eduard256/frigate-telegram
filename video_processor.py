"""
Video processor for downloading, compressing, and splitting clips from Frigate.
Handles both video clips and thumbnails for cameras with broken codecs.
"""

import asyncio
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import aiohttp

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class VideoChunk:
    """Represents a video chunk or thumbnail ready for sending."""
    file_path: Path
    part_number: int
    total_parts: int
    is_thumbnail: bool = False


@dataclass
class ProcessedEvent:
    """Represents a fully processed event ready for Telegram."""
    event_id: str
    camera: str
    label: str
    duration: int  # seconds
    chunks: List[VideoChunk]
    temp_dir: Path  # For cleanup


class VideoProcessor:
    """Handles video downloading, compression, and splitting."""

    def __init__(self, config: Config):
        self.config = config
        self.frigate_url = config.frigate_url.rstrip("/")

    async def process_event(
        self,
        event_id: str,
        camera: str,
        label: str,
        duration: float,
    ) -> Optional[ProcessedEvent]:
        """
        Process a Frigate event: download, compress, split if needed.

        Args:
            event_id: Frigate event ID
            camera: Camera name
            label: Object label (person, dog, etc.)
            duration: Event duration in seconds

        Returns:
            ProcessedEvent with file paths, or None on failure
        """
        duration_int = int(duration)

        # Create temp directory for this event
        temp_dir = Path(tempfile.mkdtemp(prefix=f"frigate_{event_id[:8]}_"))

        try:
            # Check if this camera needs thumbnail-only processing
            if camera in self.config.thumbnail_only_cameras:
                return await self._process_thumbnail(
                    event_id, camera, label, duration_int, temp_dir
                )

            # Normal video processing
            return await self._process_video(
                event_id, camera, label, duration_int, temp_dir
            )

        except Exception as e:
            logger.error(f"Error processing event {event_id}: {e}")
            # Cleanup on error
            await self._cleanup_temp_dir(temp_dir)
            return None

    async def _process_thumbnail(
        self,
        event_id: str,
        camera: str,
        label: str,
        duration: int,
        temp_dir: Path,
    ) -> Optional[ProcessedEvent]:
        """Process event as thumbnail for cameras with broken video codec."""
        thumbnail_path = temp_dir / "thumbnail.jpg"

        # Download thumbnail
        url = f"{self.frigate_url}/api/events/{event_id}/thumbnail.jpg"
        success = await self._download_file(url, thumbnail_path)

        if not success or not thumbnail_path.exists():
            logger.error(f"Failed to download thumbnail for {event_id}")
            return None

        # Check file size (should be more than just a few bytes)
        if thumbnail_path.stat().st_size < 1000:
            logger.error(f"Thumbnail too small for {event_id}, likely invalid")
            return None

        chunk = VideoChunk(
            file_path=thumbnail_path,
            part_number=1,
            total_parts=1,
            is_thumbnail=True,
        )

        return ProcessedEvent(
            event_id=event_id,
            camera=camera,
            label=label,
            duration=duration,
            chunks=[chunk],
            temp_dir=temp_dir,
        )

    async def _process_video(
        self,
        event_id: str,
        camera: str,
        label: str,
        duration: int,
        temp_dir: Path,
    ) -> Optional[ProcessedEvent]:
        """Process event as video clip with compression and splitting."""
        raw_path = temp_dir / "raw.mp4"

        # Download clip
        url = f"{self.frigate_url}/api/events/{event_id}/clip.mp4"
        success = await self._download_file(url, raw_path)

        if not success or not raw_path.exists():
            logger.error(f"Failed to download clip for {event_id}")
            return None

        # Check if video has valid video stream
        has_video = await self._check_video_stream(raw_path)
        if not has_video:
            logger.warning(f"No valid video stream in {event_id}, falling back to thumbnail")
            await self._cleanup_file(raw_path)
            return await self._process_thumbnail(event_id, camera, label, duration, temp_dir)

        # Determine if we need to split
        chunk_duration = self.config.video_chunk_duration
        if duration > chunk_duration:
            # Split into chunks
            chunks = await self._split_and_compress(raw_path, temp_dir, duration, chunk_duration)
        else:
            # Just compress
            compressed_path = temp_dir / "compressed.mp4"
            success = await self._compress_video(raw_path, compressed_path)
            if success:
                chunks = [VideoChunk(file_path=compressed_path, part_number=1, total_parts=1)]
            else:
                chunks = []

        # Cleanup raw file
        await self._cleanup_file(raw_path)

        if not chunks:
            logger.error(f"Failed to process video for {event_id}")
            return None

        return ProcessedEvent(
            event_id=event_id,
            camera=camera,
            label=label,
            duration=duration,
            chunks=chunks,
            temp_dir=temp_dir,
        )

    async def _download_file(self, url: str, dest: Path) -> bool:
        """Download file from URL to destination path."""
        try:
            timeout = aiohttp.ClientTimeout(total=self.config.download_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"Download failed: {url} returned {response.status}")
                        return False

                    with open(dest, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)

            logger.debug(f"Downloaded {url} to {dest}")
            return True

        except asyncio.TimeoutError:
            logger.error(f"Download timeout: {url}")
            return False
        except Exception as e:
            logger.error(f"Download error: {url} - {e}")
            return False

    async def _check_video_stream(self, video_path: Path) -> bool:
        """Check if video file has valid video stream using ffprobe."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(video_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return b"video" in stdout

        except Exception as e:
            logger.error(f"ffprobe error: {e}")
            return False

    async def _compress_video(self, input_path: Path, output_path: Path) -> bool:
        """Compress video using ffmpeg."""
        try:
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-i", str(input_path),
                "-vf", f"scale={self.config.video_scale}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", str(self.config.video_crf),
                "-c:a", "aac",
                "-b:a", self.config.audio_bitrate,
                "-movflags", "+faststart",
                str(output_path),
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"ffmpeg compression failed: {stderr.decode()}")
                return False

            logger.debug(f"Compressed {input_path} to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Compression error: {e}")
            return False

    async def _split_and_compress(
        self,
        input_path: Path,
        temp_dir: Path,
        total_duration: int,
        chunk_duration: int,
    ) -> List[VideoChunk]:
        """Split video into chunks and compress each."""
        chunks = []
        num_chunks = (total_duration + chunk_duration - 1) // chunk_duration

        for i in range(num_chunks):
            start_time = i * chunk_duration
            output_path = temp_dir / f"chunk_{i+1}.mp4"

            try:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss", str(start_time),
                    "-i", str(input_path),
                    "-t", str(chunk_duration),
                    "-vf", f"scale={self.config.video_scale}",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", str(self.config.video_crf),
                    "-c:a", "aac",
                    "-b:a", self.config.audio_bitrate,
                    "-movflags", "+faststart",
                    str(output_path),
                ]

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()

                if proc.returncode == 0 and output_path.exists():
                    chunks.append(VideoChunk(
                        file_path=output_path,
                        part_number=i + 1,
                        total_parts=num_chunks,
                    ))
                else:
                    logger.error(f"Failed to create chunk {i+1}")

            except Exception as e:
                logger.error(f"Error creating chunk {i+1}: {e}")

        return chunks

    async def _cleanup_file(self, path: Path):
        """Remove a single file."""
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup {path}: {e}")

    async def _cleanup_temp_dir(self, temp_dir: Path):
        """Remove temp directory and all contents."""
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Failed to cleanup {temp_dir}: {e}")

    async def cleanup_processed_event(self, event: ProcessedEvent):
        """Cleanup all temp files for a processed event."""
        await self._cleanup_temp_dir(event.temp_dir)
