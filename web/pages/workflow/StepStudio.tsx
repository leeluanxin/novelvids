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
import { Film, Video, Loader2, RefreshCw, AlertCircle, CheckSquare, Square, Trash2 } from "lucide-react"
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
  enabled: boolean
}

interface SceneGenerateResult {
  sceneId: number
  sceneSequence: number
  success: boolean
  errorMessage?: string
  completedVideoUrl?: string
}

const VIDEO_GENERATE_OPTIONS: VideoGenerateOption[] = [
  {
    key: "seedance-fast",
    label: "Seedance 2.0 Fast",
    description: "默认推荐，出图更快",
    modelType: VideoModelTypeEnum.SEEDANCE,
    modelVersion: "seedance2.0fast",
    enabled: true,
  },
  {
    key: "seedance-vip",
    label: "Seedance 2.0 VIP",
    description: "即梦高规格版本",
    modelType: VideoModelTypeEnum.SEEDANCE,
    modelVersion: "seedance2.0vip",
    enabled: true,
  },
  {
    key: "veo-3",
    label: "Veo 3",
    description: "暂未配置",
    modelType: VideoModelTypeEnum.VEO_3,
    enabled: false,
  },
  {
    key: "sora-2",
    label: "Sora 2",
    description: "暂未配置",
    modelType: VideoModelTypeEnum.SORA_2,
    enabled: false,
  },
  {
    key: "vidu-q2",
    label: "Vidu Q2",
    description: "暂未配置",
    modelType: VideoModelTypeEnum.VIDU_Q2,
    enabled: false,
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
      v.status === TaskStatusEnum.FAILED ||
      v.status === TaskStatusEnum.CANCELLED
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
  const [generateDialogMode, setGenerateDialogMode] = useState<"single" | "batch">("single")
  const [selectedOptionKey, setSelectedOptionKey] = useState(
    DEFAULT_VIDEO_GENERATE_OPTION_KEY
  )
  const [batchParallelEnabled, setBatchParallelEnabled] = useState(false)
  const [batchUsePreviousVideo, setBatchUsePreviousVideo] = useState(false)
  const [batchGenerating, setBatchGenerating] = useState(false)
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
  const batchParallelSupported = selectedGenerateOption.key === "seedance-vip"

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

  const resetGenerateDialogState = () => {
    setSelectedOptionKey(DEFAULT_VIDEO_GENERATE_OPTION_KEY)
    setBatchParallelEnabled(false)
    setBatchUsePreviousVideo(false)
  }

  const handleOpenGenerateDialog = () => {
    if (selectedScene) {
      console.info("[StepStudio] open generate dialog", {
        sceneId: selectedScene.id,
        sceneSequence: selectedScene.sequence,
      })
    }
    setGenerateDialogMode("single")
    resetGenerateDialogState()
    setGenerateDialogOpen(true)
  }

  const handleOpenBatchGenerateDialog = () => {
    console.info("[StepStudio] open batch generate dialog", {
      sceneCount: scenes.length,
    })
    setGenerateDialogMode("batch")
    resetGenerateDialogState()
    setGenerateDialogOpen(true)
  }

  const generateSceneVideo = async (
    scene: Scene,
    option: VideoGenerateOption,
    opts?: { silent?: boolean; previousVideoUrl?: string }
  ): Promise<SceneGenerateResult> => {
    const sceneId = scene.id
    const sceneSequence = scene.sequence
    const requestPayload = {
      scene_id: sceneId,
      model_type: option.modelType,
      model_version: option.modelVersion,
      previous_video_url: opts?.previousVideoUrl,
    }

    try {
      console.info("[StepStudio] generate start", {
        sceneId,
        sceneSequence,
        payload: requestPayload,
        silent: opts?.silent ?? false,
      })
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
      const sceneLabel = scenes.find((item) => item.id === sceneId)?.sequence ?? sceneId
      if (finished.status === TaskStatusEnum.COMPLETED) {
        if (!opts?.silent) {
          toast.success(`分镜 #${sceneLabel} 视频生成完成`)
        }
        return {
          sceneId,
          sceneSequence,
          success: true,
          completedVideoUrl: finished.url,
        }
      }
      const errorMessage = finished.metadata?.error || `分镜 #${sceneLabel} 视频生成失败`
      if (!opts?.silent) {
        toast.error(errorMessage)
      }
      return {
        sceneId,
        sceneSequence,
        success: false,
        errorMessage,
      }
    } catch (err) {
      console.error("[StepStudio] generate failed", {
        sceneId,
        sceneSequence,
        payload: requestPayload,
        error: err,
      })
      const errorMessage = (err as Error).message || "视频生成失败"
      if (!opts?.silent) {
        toast.error(errorMessage)
      }
      return {
        sceneId,
        sceneSequence,
        success: false,
        errorMessage,
      }
    } finally {
      console.info("[StepStudio] generate cleanup", {
        sceneId,
        sceneSequence,
      })
      setGeneratingSceneIds((current) => current.filter((id) => id !== sceneId))
    }
  }

  const handleGenerate = async () => {
    if (!selectedScene) return
    setGenerateDialogOpen(false)
    await generateSceneVideo(selectedScene, selectedGenerateOption)
  }

  const handleBatchGenerate = async () => {
    if (scenes.length === 0 || batchGenerating) return

    const option = selectedGenerateOption

    setGenerateDialogOpen(false)
    setBatchGenerating(true)

    let targetScenes: Scene[] = []

    try {
      const chapterVideosRes = await api.getChapterVideos(chapterId)
      const chapterVideoMap = new Map(
        chapterVideosRes.data.map((item) => [item.scene_id, item.video])
      )
      const firstPendingIndex = scenes.findIndex(
        (scene) => !chapterVideoMap.get(scene.id)?.url
      )

      if (firstPendingIndex === -1) {
        toast.success("当前分镜都已有视频，无需重新生成")
        return
      }

      targetScenes = scenes.slice(firstPendingIndex)

      console.info("[StepStudio] batch generate start", {
        sceneCount: targetScenes.length,
        startSceneSequence: targetScenes[0]?.sequence,
        parallel: batchParallelEnabled,
        usePreviousVideo: batchUsePreviousVideo,
        optionKey: option.key,
        modelType: option.modelType,
        modelVersion: option.modelVersion,
      })

      let results: SceneGenerateResult[] = []

      if (batchParallelEnabled) {
        const settled = await Promise.allSettled(
          targetScenes.map((scene) =>
            generateSceneVideo(scene, option, {
              silent: true,
              previousVideoUrl: batchUsePreviousVideo ? chapterVideoMap.get(scene.id)?.url : undefined,
            })
          )
        )
        results = settled.map((item, index) => {
          if (item.status === "fulfilled") {
            return item.value
          }
          return {
            sceneId: targetScenes[index].id,
            sceneSequence: targetScenes[index].sequence,
            success: false,
            errorMessage: item.reason instanceof Error ? item.reason.message : "视频生成失败",
          }
        })
      } else {
        let previousVideoUrl: string | undefined
        if (batchUsePreviousVideo) {
          for (let index = firstPendingIndex - 1; index >= 0; index -= 1) {
            const previousScene = scenes[index]
            const previousVideo = chapterVideoMap.get(previousScene.id)
            if (previousVideo?.url) {
              previousVideoUrl = previousVideo.url
              break
            }
          }
        }

        for (const scene of targetScenes) {
          const result = await generateSceneVideo(scene, option, {
            silent: true,
            previousVideoUrl: batchUsePreviousVideo ? previousVideoUrl : undefined,
          })
          results.push(result)
          previousVideoUrl = batchUsePreviousVideo && result.success ? result.completedVideoUrl : undefined
        }
      }

      const successCount = results.filter((item) => item.success).length
      const failedResults = results.filter((item) => !item.success)

      if (failedResults.length === 0) {
        toast.success(`批量生成完成：${successCount} 成功`)
      } else {
        const failedSequences = failedResults
          .slice(0, 5)
          .map((item) => `#${item.sceneSequence}`)
          .join("、")
        toast.error(
          `批量生成完成：${successCount} 成功，${failedResults.length} 失败${failedSequences ? `（失败分镜：${failedSequences}）` : ""}`
        )
      }
    } finally {
      console.info("[StepStudio] batch generate cleanup", {
        sceneCount: targetScenes.length,
      })
      setBatchGenerating(false)
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

  const handleDeleteVideo = async (video: VideoType) => {
    try {
      await api.deleteVideo(video.id)
      setVideos((prev) => prev.filter((item) => item.id !== video.id))
      toast.success(`视频 #${video.id} 已删除`)
    } catch (err) {
      toast.error((err as Error).message || "删除视频失败")
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
                      {generatingSceneIds.includes(scene.id) && (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                      )}
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
        <div className="p-4 border-t">
          <Button
            className="w-full"
            variant="secondary"
            onClick={handleOpenBatchGenerateDialog}
            disabled={batchGenerating}
          >
            {batchGenerating ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                批量生成中...
              </>
            ) : (
              <>
                <Video className="h-4 w-4 mr-2" />
                一键生成
              </>
            )}
          </Button>
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
                  <div className="absolute top-3 right-3 flex items-center gap-2">
                    <Badge variant="secondary">
                      {modelLabel(latestVideo.model_type)}
                    </Badge>
                    <Button
                      size="icon"
                      variant="secondary"
                      className="h-8 w-8"
                      onClick={() => handleDeleteVideo(latestVideo)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
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
                          <div className="flex items-center gap-1">
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-6 w-6"
                              onClick={() => handleRefresh(video.id)}
                            >
                              <RefreshCw className="h-3 w-3" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-6 w-6 text-red-500 hover:text-red-500"
                              onClick={() => handleDeleteVideo(video)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
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
        <Dialog
          open={generateDialogOpen}
          onOpenChange={(open) => {
            if (batchGenerating) {
              return
            }
            setGenerateDialogOpen(open)
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{generateDialogMode === "batch" ? "一键生成视频" : "选择视频模型"}</DialogTitle>
              <DialogDescription>
                默认推荐 Seedance 2.0 Fast，也可以切换到其他模型后再生成。
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              {VIDEO_GENERATE_OPTIONS.map((option) => {
                const isSelected = option.key === selectedOptionKey
                const isDisabled = !option.enabled
                return (
                  <button
                    key={option.key}
                    type="button"
                    disabled={isDisabled}
                    className={`w-full rounded-lg border p-4 text-left transition-colors ${
                      isDisabled
                        ? "border-border bg-muted/20 text-muted-foreground cursor-not-allowed opacity-60"
                        : isSelected
                          ? "border-primary bg-primary/5"
                          : "border-border hover:bg-muted/50"
                    }`}
                    onClick={() => {
                      if (isDisabled) {
                        return
                      }
                      setSelectedOptionKey(option.key)
                      if (option.key !== "seedance-vip") {
                        setBatchParallelEnabled(false)
                      }
                    }}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-start gap-3 min-w-0">
                        {isSelected && !isDisabled ? (
                          <CheckSquare className="h-5 w-5 mt-0.5 text-primary shrink-0" />
                        ) : (
                          <Square className="h-5 w-5 mt-0.5 text-muted-foreground shrink-0" />
                        )}
                        <div>
                          <div className="font-medium">{option.label}</div>
                          <div className="text-sm text-muted-foreground mt-1">
                            {option.description}
                          </div>
                        </div>
                      </div>
                      {isDisabled ? <Badge variant="outline">暂不可用</Badge> : isSelected ? <Badge>已选择</Badge> : null}
                    </div>
                  </button>
                )
              })}
            </div>

            {generateDialogMode === "batch" && (
              <div className="rounded-lg border p-4 space-y-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="font-medium">是否参考上一段</div>
                    <div className="text-sm text-muted-foreground mt-1">
                      勾选后才会把上一段视频作为续接参考，默认关闭。
                    </div>
                  </div>
                  <button
                    type="button"
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${
                      batchUsePreviousVideo
                        ? "border-primary bg-primary/5 text-foreground"
                        : "border-border hover:bg-muted/50 text-foreground"
                    }`}
                    onClick={() => setBatchUsePreviousVideo((value) => !value)}
                  >
                    {batchUsePreviousVideo ? (
                      <CheckSquare className="h-4 w-4 text-primary shrink-0" />
                    ) : (
                      <Square className="h-4 w-4 text-muted-foreground shrink-0" />
                    )}
                    <span>{batchUsePreviousVideo ? "已参考上一段" : "不参考上一段"}</span>
                  </button>
                </div>

                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="font-medium">是否并行</div>
                    <div className="text-sm text-muted-foreground mt-1">
                      {batchParallelSupported
                        ? "当前模型支持并行生成，可按需开启。"
                        : "当前模型暂不支持并行生成。"}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={!batchParallelSupported}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${
                      !batchParallelSupported
                        ? "border-border bg-muted/20 text-muted-foreground cursor-not-allowed opacity-60"
                        : batchParallelEnabled
                          ? "border-primary bg-primary/5 text-foreground"
                          : "border-border hover:bg-muted/50 text-foreground"
                    }`}
                    onClick={() => setBatchParallelEnabled((value) => !value)}
                  >
                    {batchParallelEnabled ? (
                      <CheckSquare className="h-4 w-4 text-primary shrink-0" />
                    ) : (
                      <Square className="h-4 w-4 text-muted-foreground shrink-0" />
                    )}
                    <span>{batchParallelEnabled ? "并行已开启" : "并行已关闭"}</span>
                  </button>
                </div>
              </div>
            )}

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setGenerateDialogOpen(false)}
                disabled={generateDialogMode === "batch" ? batchGenerating : isSelectedSceneGenerating}
              >
                取消
              </Button>
              <Button
                onClick={generateDialogMode === "batch" ? handleBatchGenerate : handleGenerate}
                disabled={generateDialogMode === "batch" ? batchGenerating : isSelectedSceneGenerating}
              >
                {generateDialogMode === "batch" && batchGenerating ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    生成中...
                  </>
                ) : (
                  "开始生成"
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  )
}
