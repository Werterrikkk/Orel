import { existsSync, statSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

export default function prepareCameraFixture() {
  const source = fileURLToPath(new URL('../../data/demo.mp4', import.meta.url))
  const target = fileURLToPath(new URL('../../data/e2e-camera.y4m', import.meta.url))
  const unhelmeted = fileURLToPath(
    new URL('../../data/datasets/ppe3/images/test/image1120.jpg', import.meta.url),
  )
  if (!existsSync(source))
    throw new Error('Подготовьте учебный ролик: python -m scripts.prepare_demo')
  if (!existsSync(unhelmeted)) throw new Error('Подготовьте тестовую выборку Construction-PPE.')
  const setup = fileURLToPath(import.meta.url)
  if (
    existsSync(target) &&
    statSync(target).mtimeMs >=
      Math.max(statSync(source).mtimeMs, statSync(unhelmeted).mtimeMs, statSync(setup).mtimeMs)
  )
    return
  // Real public test photos with present/missing helmets; never fabricated detections.
  execFileSync(
    'ffmpeg',
    [
      '-y',
      '-loglevel',
      'error',
      '-i',
      source,
      '-loop',
      '1',
      '-i',
      unhelmeted,
      '-filter_complex',
      '[0:v]trim=start=6:end=11,setpts=PTS-STARTPTS,scale=640:360,setsar=1,fps=10[a];[1:v]trim=duration=16,setpts=PTS-STARTPTS,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=10[b];[a][b]concat=n=2:v=1:a=0,format=yuv420p[v]',
      '-map',
      '[v]',
      '-f',
      'yuv4mpegpipe',
      target,
    ],
    { timeout: 30_000 },
  )
}
