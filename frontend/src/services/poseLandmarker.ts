import { FilesetResolver, PoseLandmarker } from '@mediapipe/tasks-vision'

export interface PoseLandmarkPoint {
  x: number
  y: number
  z: number
  visibility: number
}

export interface PoseFrameData {
  timestamp_ms: number
  landmarks: PoseLandmarkPoint[]
}

export interface PoseLandmarkPayload {
  model: string
  duration_ms: number
  frames: PoseFrameData[]
}

let videoLandmarkerPromise: Promise<PoseLandmarker> | null = null
let imageLandmarkerPromise: Promise<PoseLandmarker> | null = null

async function createLandmarker(runningMode: 'VIDEO' | 'IMAGE') {
  const vision = await FilesetResolver.forVisionTasks('/mediapipe/wasm')
  const options = {
    runningMode,
    numPoses: 1,
    minPoseDetectionConfidence: 0.5,
    minPosePresenceConfidence: 0.5,
    minTrackingConfidence: 0.5,
    outputSegmentationMasks: false,
  } as const
  try {
    return await PoseLandmarker.createFromOptions(vision, {
      ...options,
      baseOptions: {
        modelAssetPath: '/mediapipe/models/pose_landmarker_lite.task',
        delegate: 'GPU',
      },
    })
  } catch {
    return PoseLandmarker.createFromOptions(vision, {
      ...options,
      baseOptions: {
        modelAssetPath: '/mediapipe/models/pose_landmarker_lite.task',
        delegate: 'CPU',
      },
    })
  }
}

function getVideoLandmarker() {
  videoLandmarkerPromise ||= createLandmarker('VIDEO')
  return videoLandmarkerPromise
}

function getImageLandmarker() {
  imageLandmarkerPromise ||= createLandmarker('IMAGE')
  return imageLandmarkerPromise
}

function waitForEvent(target: EventTarget, eventName: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup()
      reject(new Error(`等待 ${eventName} 超时`))
    }, 15000)
    const cleanup = () => {
      window.clearTimeout(timeout)
      target.removeEventListener(eventName, onDone)
      target.removeEventListener('error', onError)
    }
    const onDone = () => {
      cleanup()
      resolve()
    }
    const onError = () => {
      cleanup()
      reject(new Error('媒体文件加载失败'))
    }
    target.addEventListener(eventName, onDone, { once: true })
    target.addEventListener('error', onError, { once: true })
  })
}

function normalizeLandmarks(landmarks: Array<{ x: number; y: number; z: number; visibility?: number }>) {
  return landmarks.map(point => ({
    x: Number(point.x.toFixed(6)),
    y: Number(point.y.toFixed(6)),
    z: Number(point.z.toFixed(6)),
    visibility: Number((point.visibility ?? 0).toFixed(4)),
  }))
}

function adaptiveFrameCount(durationSeconds: number) {
  if (durationSeconds <= 6) return 12
  if (durationSeconds <= 15) return 18
  return 24
}

export async function analyzePoseImage(file: File): Promise<PoseLandmarkPayload> {
  const image = new Image()
  image.src = URL.createObjectURL(file)
  try {
    await waitForEvent(image, 'load')
    const landmarker = await getImageLandmarker()
    const result = landmarker.detect(image)
    return {
      model: 'mediapipe_pose_landmarker_lite',
      duration_ms: 0,
      frames: result.landmarks[0]
        ? [{ timestamp_ms: 0, landmarks: normalizeLandmarks(result.landmarks[0]) }]
        : [],
    }
  } finally {
    URL.revokeObjectURL(image.src)
  }
}

export async function analyzePoseVideo(file: File): Promise<{
  frames: File[]
  payload: PoseLandmarkPayload
}> {
  const video = document.createElement('video')
  video.preload = 'metadata'
  video.muted = true
  video.playsInline = true
  video.src = URL.createObjectURL(file)

  try {
    await waitForEvent(video, 'loadedmetadata')
    const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 1
    const landmarker = await getVideoLandmarker()
    const sampleCount = adaptiveFrameCount(duration)
    const timestamps = Array.from(
      { length: sampleCount },
      (_, index) => Math.min(duration * ((index + 0.5) / sampleCount), Math.max(duration - 0.03, 0)),
    )
    const canvas = document.createElement('canvas')
    const width = Math.min(video.videoWidth || 720, 960)
    const height = Math.max(1, Math.round(width * ((video.videoHeight || 540) / (video.videoWidth || 720))))
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('无法创建视频分析画布')

    const payloadFrames: PoseFrameData[] = []
    const previewFrames: File[] = []
    for (let index = 0; index < timestamps.length; index += 1) {
      const timestampSeconds = timestamps[index]
      video.currentTime = timestampSeconds
      await waitForEvent(video, 'seeked')
      const timestampMs = Math.round(timestampSeconds * 1000)
      const result = landmarker.detectForVideo(video, timestampMs)
      if (result.landmarks[0]) {
        payloadFrames.push({
          timestamp_ms: timestampMs,
          landmarks: normalizeLandmarks(result.landmarks[0]),
        })
      }
      // Vision Model only receives six representative frames; geometry uses all sampled frames.
      if (index % Math.max(1, Math.floor(sampleCount / 6)) === 0 && previewFrames.length < 6) {
        context.drawImage(video, 0, 0, width, height)
        const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.82))
        if (blob) {
          previewFrames.push(new File([blob], `pose_frame_${previewFrames.length}.jpg`, { type: 'image/jpeg' }))
        }
      }
    }
    return {
      frames: previewFrames,
      payload: {
        model: 'mediapipe_pose_landmarker_lite',
        duration_ms: Math.round(duration * 1000),
        frames: payloadFrames,
      },
    }
  } finally {
    URL.revokeObjectURL(video.src)
  }
}
