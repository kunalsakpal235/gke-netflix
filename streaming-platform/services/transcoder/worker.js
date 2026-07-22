// Consumes a VIDEO_ID (from a Pub/Sub push or Job env) and would transcode MP4 -> HLS with ffmpeg,
// writing segments to Cloud Storage. Placeholder body for the scaffold.
import { execSync } from 'node:child_process';
const id = process.env.VIDEO_ID || 'unknown';
console.log(`transcoding video ${id} -> HLS ...`);
// execSync(`ffmpeg -i input.mp4 -codec: copy -hls_time 6 -f hls out/${id}.m3u8`);
console.log('done');
