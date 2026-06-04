import { useEffect, useMemo, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Film, Video, Loader2, RefreshCw, AlertCircle } from "lucide-react"
import { api } from "@/services/api"
import type { Scene, Video as VideoType } from "@/types"
import { TaskStatusEnum, VideoModelTypeEnum } from "@/types"
import { toast } from "sonner"
import { sleep, statusLabel, statusColor, modelLabel } from "@/lib/helpers"

interface StepStudioProps {
  chapterId: number
}

interface VideoGenerateOption {
  key: string
  label: string
  description: string
  modelType: VideoModelTypeEnum
  modelVersion?: string
}

const VIDEO_GENERATE_OPTIONS: VideoGenerateOption[] = [
  {
    key: "seedance-fast",
    label: "Seedance 2.0 Fast",
    description: "默认推荐，出图更快",
    modelType: VideoModelTypeEnum.SEEDANCE,
    modelVersion: "seedance2.0fast",
  },
  {
    key: "seedance-vip",
    label: "Seedance 2.0 VIP",
    description: "即梦高规格版本",
    modelType: VideoModelTypeEnum.SEEDANCE,
    modelVersion: "seedance2.0vip",
  },
  {
    key: "veo-3",
    label: "Veo 3",
    description: "高质量生成",
    modelType: VideoModelTypeEnum.VEO_3,
  },
  {
    key: "sora-2",
    label: "Sora 2",
    description: "OpenAI 视频模型",
    modelType: VideoModelTypeEnum.SORA_2,
  },
  {
    key: "vidu-q2",
    label: "Vidu Q2",
    description: "轻量快速生成",
    modelType: VideoModelTypeEnum.VIDU_Q2,
  },
]

const DEFAULT_VIDEO_GENERATE_OPTION_KEY = VIDEO_GENERATE_OPTIONS[0].key

async function pollVideo(videoId: number): Promise<VideoType> {
  while (true) {
    await sleep(4000)
    const res = await api.queryVideo(videoId)
    const v = res.data
    if (
      v.status === TaskStatusEnum.COMPLETED ||
      v.status === TaskStatusEnum.FAILED
    ) {
      return v
    }
  }
}

export const StepStudio = ({ chapterId }: StepStudioProps) => {
  const [scenes, setScenes] = useState<Scene[]>([])
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null)
  const [videos, setVideos] = useState<VideoType[]>([])
  const [generatingSceneIds, setGeneratingSceneIds] = useState<number[]>([])
  const [loading, setLoading] = useState(true)
  const [generateDialogOpen, setGenerateDialogOpen] = useState(false)
  const [selectedOptionKey, setSelectedOptionKey] = useState(
    DEFAULT_VIDEO_GENERATE_OPTION_KEY
  )
  const selectedSceneIdRef = useRef<number | null>(null)

  const loadScenes = async () => {
    try {
      setLoading(true)
      const res = await api.getScenes(chapterId)
      const items = res.data.items
      setScenes(items)
      if (items.length > 0 && !selectedScene) {
        setSelectedScene(items[0])
      }
    } catch (err) {
      toast.error((err as Error).message || "加载场景列表失败")
    } finally {
      setLoading(false)
    }
  }

  const loadVideos = async (sceneId: number) => {
    try {
      const res = await api.getVideos(1, 100, "-id", sceneId)
      setVideos(mergeUniqueVideos(res.data.items))
    } catch (err) {
      toast.error((err as Error).message || "加载视频列表失败")
    }
  }

  useEffect(() => {
    loadScenes()
  }, [chapterId])

  useEffect(() => {
    selectedSceneIdRef.current = selectedScene?.id ?? null
    if (selectedScene) {
      loadVideos(selectedScene.id)
    } else {
      setVideos([])
    }
  }, [selectedScene?.id])

  const latestVideo = videos.length > 0 ? videos[0] : null
  const isSelectedSceneGenerating =
    selectedScene != null && generatingSceneIds.includes(selectedScene.id)
  const selectedGenerateOption = useMemo(
    () =>
      VIDEO_GENERATE_OPTIONS.find((option) => option.key === selectedOptionKey) ??
      VIDEO_GENERATE_OPTIONS[0],
    [selectedOptionKey]
  )

  const mergeUniqueVideos = (items: VideoType[]) => {
    const seen = new Set<number>()
    return items.filter((video) => {
      if (seen.has(video.id)) {
        return false
      }
      seen.add(video.id)
      return true
    })
  }

  const handleOpenGenerateDialog = () => {
    if (selectedScene) {
      console.info("[StepStudio] open generate dialog", {
        sceneId: selectedScene.id,
        sceneSequence: selectedScene.sequence,
      })
    }
    setSelectedOptionKey(DEFAULT_VIDEO_GENERATE_OPTION_KEY)
    setGenerateDialogOpen(true)
  }

  const handleGenerate = async () => {
    if (!selectedScene) return

    const sceneId = selectedScene.id
    const sceneSequence = selectedScene.sequence
    const requestPayload = {
      scene_id: sceneId,
      model_type: selectedGenerateOption.modelType,
      model_version: selectedGenerateOption.modelVersion,
    }

    try {
      console.info("[StepStudio] generate start", {
        sceneId,
        sceneSequence,
        payload: requestPayload,
      })
      setGenerateDialogOpen(false)
      setGeneratingSceneIds((current) =>
        current.includes(sceneId) ? current : [...current, sceneId]
      )
      const res = await api.generateVideo(requestPayload)
      const newVideo = res.data
      console.info("[StepStudio] generate request success", {
        sceneId,
        sceneSequence,
        videoId: newVideo.id,
        externalTaskId: newVideo.external_task_id,
        status: newVideo.status,
      })
      if (selectedSceneIdRef.current === sceneId) {
        setVideos((prev) => mergeUniqueVideos([newVideo, ...prev]))
      }
      const finished = await pollVideo(newVideo.id)
      console.info("[StepStudio] generate poll finished", {
        sceneId,
        sceneSequence,
        videoId: finished.id,
        status: finished.status,
        url: finished.url,
        metadata: finished.metadata,
      })
      if (selectedSceneIdRef.current === sceneId) {
        setVideos((prev) =>
          mergeUniqueVideos(prev.map((v) => (v.id === finished.id ? finished : v)))
        )
      }
      const sceneLabel = scenes.find((scene) => scene.id === sceneId)?.sequence ?? sceneId
      if (finished.status === TaskStatusEnum.COMPLETED) {
        toast.success(`分镜 #${sceneLabel} 视频生成完成`)
      } else {
        toast.error(finished.metadata?.error || `分镜 #${sceneLabel} 视频生成失败`)
      }
    } catch (err) {
      console.error("[StepStudio] generate failed", {
        sceneId,
        sceneSequence,
        payload: requestPayload,
        error: err,
      })
      toast.error((err as Error).message || "视频生成失败")
    } finally {
      console.info("[StepStudio] generate cleanup", {
        sceneId,
        sceneSequence,
      })
      setGeneratingSceneIds((current) => current.filter((id) => id !== sceneId))
    }
  }

  const handleRefresh = async (videoId: number) => {
    try {
      const res = await api.queryVideo(videoId)
      setVideos((prev) =>
        mergeUniqueVideos(prev.map((v) => (v.id === videoId ? res.data : v)))
      )
    } catch (err) {
      toast.error((err as Error).message || "刷新视频状态失败")
    }
  }

  const handleSelectScene = (scene: Scene) => {
    setSelectedScene(scene)
  }

  const isProcessing = (v: VideoType) =>
    v.status === TaskStatusEnum.PROCESSING ||
    v.status === TaskStatusEnum.PENDING ||
    v.status === TaskStatusEnum.QUEUED

  return (
    <div className="flex h-full">
      {/* Left panel - scene list */}
      <div className="w-72 bg-card border-r flex flex-col">
        <div className="p-4 border-b">
          <h3 className="font-semibold">场景列表</h3>
        </div>
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="p-2 space-y-1">
              {scenes.map((scene) => {
                const isActive = selectedScene?.id === scene.id
                return (
                  <div
                    key={scene.id}
                    className={`p-3 rounded-lg cursor-pointer transition-colors border ${
                      isActive
                        ? "bg-primary/10 border-primary"
                        : "border-transparent hover:bg-secondary/50"
                    }`}
                    onClick={() => handleSelectScene(scene)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-muted-foreground">
                        #{scene.sequence}
                      </span>
                      {scene.duration != null && (
                        <span className="text-xs text-muted-foreground">
                          {scene.duration}秒
                        </span>
                      )}
                    </div>
                    <p className="text-sm mt-1 line-clamp-2 text-muted-foreground">
                      {scene.description || "暂无描述"}
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Right area */}
      <div className="flex-1 p-6 flex flex-col gap-6 overflow-auto">
        {!selectedScene ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            请从左侧选择一个场景
          </div>
        ) : (
          <>
            {/* Preview area */}
            <div className="flex-1 bg-black/40 rounded-lg border flex items-center justify-center min-h-[300px] relative overflow-hidden">
              {latestVideo &&
              latestVideo.status === TaskStatusEnum.COMPLETED &&
              latestVideo.url ? (
                <div className="w-full h-full relative">
                  <video
                    src={latestVideo.url}
                    controls
                    className="w-full h-full object-contain"
                  />
                  <div className="absolute top-3 right-3">
                    <Badge variant="secondary">
                      {modelLabel(latestVideo.model_type)}
                    </Badge>
                  </div>
                </div>
              ) : latestVideo && isProcessing(latestVideo) ? (
                <div className="flex flex-col items-center gap-3 text-muted-foreground">
                  <Loader2 className="h-10 w-10 animate-spin" />
                  <p className="text-sm font-medium">视频生成中...</p>
                  <Badge variant="secondary">
                    {modelLabel(latestVideo.model_type)}
                  </Badge>
                  <Badge variant="outline">
                    {statusLabel(latestVideo.status)}
                  </Badge>
                </div>
              ) : latestVideo && latestVideo.status === TaskStatusEnum.FAILED ? (
                <div className="flex flex-col items-center gap-3 text-muted-foreground max-w-md text-center">
                  <AlertCircle className="h-10 w-10 text-red-500" />
                  <p className="text-sm font-medium text-red-400">视频生成失败</p>
                  {latestVideo.metadata?.error && (
                    <p className="text-xs text-red-400/80 bg-red-500/10 rounded-lg px-4 py-2">
                      {latestVideo.metadata.error}
                    </p>
                  )}
                  <Badge variant="secondary">
                    {modelLabel(latestVideo.model_type)}
                  </Badge>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3 text-muted-foreground">
                  <Film className="h-12 w-12" />
                  <p className="text-sm">暂无生成视频</p>
                </div>
              )}
            </div>

            {/* Control panel */}
            <div className="bg-card border rounded-xl p-6 space-y-4">
              {/* Prompt display */}
              <div>
                <label className="text-sm font-medium text-muted-foreground mb-2 block">
                  提示词
                </label>
                <div className="bg-background font-mono text-sm p-3 rounded-lg border min-h-[60px]">
                  {selectedScene.prompt || "暂无提示词"}
                </div>
              </div>

              {/* Controls row */}
              <div className="flex items-center gap-3">
                {/* Generate button */}
                <Button
                  onClick={handleOpenGenerateDialog}
                  disabled={isSelectedSceneGenerating}
                >
                  {isSelectedSceneGenerating ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      生成中...
                    </>
                  ) : (
                    <>
                      <Video className="h-4 w-4 mr-2" />
                      {videos.length > 0 ? "重新生成视频" : "生成视频"}
                    </>
                  )}
                </Button>
              </div>

              {/* Video history */}
              {videos.length > 1 && (
                <div>
                  <label className="text-sm font-medium text-muted-foreground mb-2 block">
                    历史版本
                  </label>
                  <div className="flex gap-3 overflow-x-auto pb-2">
                    {videos.map((video) => (
                      <Card
                        key={video.id}
                        className="shrink-0 p-3 w-44 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono text-muted-foreground">
                            #{video.id}
                          </span>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-6 w-6"
                            onClick={() => handleRefresh(video.id)}
                          >
                            <RefreshCw className="h-3 w-3" />
                          </Button>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary" className="text-xs">
                            {modelLabel(video.model_type)}
                          </Badge>
                          <Badge variant="outline" className="text-xs">
                            {statusLabel(video.status)}
                          </Badge>
                        </div>
                        {video.status === TaskStatusEnum.FAILED && video.metadata?.error && (
                          <p className="text-xs text-red-400 line-clamp-2">
                            {video.metadata.error}
                          </p>
                        )}
                      </Card>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
        <Dialog open={generateDialogOpen} onOpenChange={setGenerateDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>选择视频模型</DialogTitle>
              <DialogDescription>
                默认推荐 Seedance 2.0 Fast，也可以切换到其他模型后再生成。
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              {VIDEO_GENERATE_OPTIONS.map((option) => {
                const isSelected = option.key === selectedOptionKey
                return (
                  <button
                    key={option.key}
                    type="button"
                    className={`w-full rounded-lg border p-4 text-left transition-colors ${
                      isSelected
                        ? "border-primary bg-primary/5"
                        : "border-border hover:bg-muted/50"
                    }`}
                    onClick={() => setSelectedOptionKey(option.key)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium">{option.label}</div>
                        <div className="text-sm text-muted-foreground mt-1">
                          {option.description}
                        </div>
                      </div>
                      {isSelected && <Badge>已选择</Badge>}
                    </div>
                  </button>
                )
              })}
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setGenerateDialogOpen(false)}
                disabled={isSelectedSceneGenerating}
              >
                取消
              </Button>
              <Button onClick={handleGenerate} disabled={isSelectedSceneGenerating}>
                开始生成
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  )
}
