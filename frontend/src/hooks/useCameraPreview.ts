import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

// Media playback has its own lifecycle. A cancelled play() is not camera failure.
export function useCameraPreview(
  videoRef: RefObject<HTMLVideoElement | null>,
  stream: MediaStream | null,
) {
  const [blocked, setBlocked] = useState(false)
  const resume = useRef<() => void>(() => {})
  useEffect(() => {
    const video = videoRef.current
    setBlocked(false)
    if (!video || !stream) return
    let active = true
    video.muted = true
    video.defaultMuted = true
    video.playsInline = true
    video.setAttribute('muted', '')
    video.setAttribute('playsinline', '')
    if (video.srcObject !== stream) video.srcObject = stream
    const play = () => {
      if (!active || video.srcObject !== stream) return
      void video.play().then(
        () => {
          if (active) setBlocked(false)
        },
        (error: unknown) => {
          if (!active || video.srcObject !== stream) return
          if (error instanceof DOMException && error.name === 'AbortError') return
          setBlocked(true)
        },
      )
    }
    resume.current = play
    video.addEventListener('loadedmetadata', play)
    video.addEventListener('canplay', play)
    if (video.readyState >= 1) play()
    return () => {
      active = false
      resume.current = () => {}
      video.removeEventListener('loadedmetadata', play)
      video.removeEventListener('canplay', play)
      if (video.srcObject === stream) {
        video.pause()
        video.srcObject = null
      }
    }
  }, [videoRef, stream])
  return { blocked, resume: useCallback(() => resume.current(), []) }
}
