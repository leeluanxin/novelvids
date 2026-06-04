import { useEffect, useState, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  Image as ImageIcon,
  Loader2,
  RefreshCw,
  Sparkles,
  Pencil,
  Trash2,
  Upload,
  User,
  MapPin,
  Box,
  Mic,
  Play,
  Video,
} from "lucide-react"
import { api } from "@/services/api"
import type { Asset, AiTask } from "@/types"
import { AssetTypeEnum, TaskStatusEnum } from "@/types"
import { toast } from "sonner"
import { sleep } from "@/lib/helpers"

interface StepAssetsProps {
  chapterId: number
  novelId: number
}

async function pollTask(taskId: string): Promise<AiTask> {
  while (true) {
    await sleep(10000)
    const res = await api.getTask(taskId)
    const t = res.data
    if (
      t.status === TaskStatusEnum.COMPLETED ||
      t.status === TaskStatusEnum.FAILED ||
      t.status === TaskStatusEnum.CANCELLED
    )
      return t
  }
}

export const StepAssets = ({ chapterId: _chapterId, novelId }: StepAssetsProps) => {
  const [assets, setAssets] = useState<Asset[]>([])
  const [loading, setLoading] = useState(true)
  const [processingIds, setProcessingIds] = useState<Set<number>>(new Set())
  const [batchGenerating, setBatchGenerating] = useState(false)

  // Edit dialog state
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null)
  const [editForm, setEditForm] = useState({
    canonical_name: "",
    aliases: "",
    description: "",
    base_traits: "",
  })
  const [saving, setSaving] = useState(false)

  // Upload refs
  const uploadRef1 = useRef<HTMLInputElement>(null)
  const uploadRef2 = useRef<HTMLInputElement>(null)
  const uploadRefMain = useRef<HTMLInputElement>(null)
  const uploadRefAudio = useRef<HTMLInputElement>(null)
  const uploadRefVideo = useRef<HTMLInputElement>(null)
  const [uploadingField, setUploadingField] = useState<string | null>(null)

  const loadAssets = async () => {
    try {
      const res = await api.getAssets(novelId)
      setAssets(res.data.items)
    } catch (err) {
      toast.error((err as Error).message || "加载资产失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAssets()
  }, [novelId])

  const handleGenerate = async (assetId: number) => {
    setProcessingIds((prev) => new Set(prev).add(assetId))
    try {
      const res = await api.generateAssetImage(assetId)
      const task = await pollTask(res.data.id)
      if (task.status === TaskStatusEnum.COMPLETED) {
        toast.success("参考图生成完成")
      } else {
        toast.error(task.error_message || "参考图生成失败")
      }
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "参考图生成失败")
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev)
        next.delete(assetId)
        return next
      })
    }
  }

  const handleBatchGenerate = async () => {
    const missing = assets.filter((a) => a.asset_type !== AssetTypeEnum.GENERAL && !a.main_image)
    if (missing.length === 0) {
      toast.info("所有资产都已有主图")
      return
    }
    setBatchGenerating(true)
    let success = 0
    let failed = 0
    for (const asset of missing) {
      try {
        setProcessingIds((prev) => new Set(prev).add(asset.id))
        const res = await api.generateAssetImage(asset.id)
        const task = await pollTask(res.data.id)
        if (task.status === TaskStatusEnum.COMPLETED) {
          success++
        } else {
          toast.error(task.error_message || "参考图生成失败")
          failed++
        }
      } catch {
        failed++
      } finally {
        setProcessingIds((prev) => {
          const next = new Set(prev)
          next.delete(asset.id)
          return next
        })
        await loadAssets()
      }
    }
    setBatchGenerating(false)
    toast.success(`批量生成完成：${success} 成功${failed > 0 ? `，${failed} 失败` : ""}`)
  }

  // Edit handlers
  const handleEditOpen = (asset: Asset) => {
    setEditingAsset(asset)
    setEditForm({
      canonical_name: asset.canonical_name || "",
      aliases: asset.aliases?.join(", ") || "",
      description: asset.description || "",
      base_traits: asset.base_traits || "",
    })
  }

  const handleEditSave = async () => {
    if (!editingAsset) return
    try {
      setSaving(true)
      await api.updateAsset(editingAsset.id, {
        canonical_name: editForm.canonical_name.trim(),
        aliases: editForm.aliases
          ? editForm.aliases.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
          : [],
        description: editForm.description.trim() || undefined,
        base_traits: editForm.base_traits.trim() || undefined,
      })
      toast.success("资产已更新")
      setEditingAsset(null)
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "更新失败")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (asset: Asset) => {
    if (!confirm(`确定要删除「${asset.canonical_name}」吗？`)) return
    try {
      await api.deleteAsset(asset.id)
      toast.success("已删除")
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "删除失败")
    }
  }

  // Upload handler for images (main + sub-reference)
  const handleUpload = async (assetId: number, field: "main_image" | "angle_image_1" | "angle_image_2" | "audio_url" | "video_url", file: File) => {
    setUploadingField(field)
    try {
      const res = await api.uploadFiles([file])
      const uploaded = res.data.files[0]
      const url = `/media/${uploaded.filename}`
      await api.updateAsset(assetId, { [field]: url })
      toast.success(
        field === "audio_url"
          ? "音频已上传"
          : field === "video_url"
            ? "视频已上传"
            : "图片已上传"
      )
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "上传失败")
    } finally {
      setUploadingField(null)
    }
  }

  const missingCount = assets.filter((a) => a.asset_type !== AssetTypeEnum.GENERAL && !a.main_image).length

  const sections = [
    { label: "角色", icon: User, color: "border-blue-500", textColor: "text-blue-500", data: assets.filter((a) => a.asset_type === AssetTypeEnum.PERSON) },
    { label: "场景", icon: MapPin, color: "border-green-500", textColor: "text-green-500", data: assets.filter((a) => a.asset_type === AssetTypeEnum.SCENE) },
    { label: "道具", icon: Box, color: "border-amber-500", textColor: "text-amber-500", data: assets.filter((a) => a.asset_type === AssetTypeEnum.ITEM) },
    { label: "通用", icon: Mic, color: "border-violet-500", textColor: "text-violet-500", data: assets.filter((a) => a.asset_type === AssetTypeEnum.GENERAL) },
  ]

  const renderAssetCard = (asset: Asset) => {
    const isGeneral = asset.asset_type === AssetTypeEnum.GENERAL
    const hasImage = !!asset.main_image
    const hasAudio = !!asset.audio_url
    const hasVideo = !!asset.video_url

    if (isGeneral) {
      return (
        <Card key={asset.id} className="overflow-hidden">
          <div className="p-4 space-y-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-12 h-12 rounded-xl bg-secondary flex items-center justify-center shrink-0">
                <Mic className="h-5 w-5 text-muted-foreground" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm truncate">{asset.canonical_name}</span>
                  {hasAudio && <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />}
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <div className="rounded-lg border bg-secondary/20 p-3 space-y-2">
                <div className="text-xs text-muted-foreground">音频参考</div>
                {hasAudio ? (
                  <audio controls className="w-full" src={asset.audio_url} />
                ) : (
                  <div className="h-10 rounded bg-secondary/40 flex items-center justify-center text-xs text-muted-foreground">
                    暂无音频
                  </div>
                )}
              </div>

              <div className="rounded-lg border bg-secondary/20 p-3 space-y-2">
                <div className="text-xs text-muted-foreground">视频参考</div>
                {hasVideo ? (
                  <video controls className="w-full rounded" src={asset.video_url} />
                ) : (
                  <div className="h-20 rounded bg-secondary/40 flex items-center justify-center text-xs text-muted-foreground">
                    暂无视频
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={uploadingField === "audio_url"}
                onClick={() => {
                  uploadRefAudio.current?.setAttribute("data-asset-id", String(asset.id))
                  uploadRefAudio.current?.click()
                }}
              >
                <Upload className="h-3.5 w-3.5 mr-1" />
                {hasAudio ? "重新上传音频" : "上传音频"}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={uploadingField === "video_url"}
                onClick={() => {
                  uploadRefVideo.current?.setAttribute("data-asset-id", String(asset.id))
                  uploadRefVideo.current?.click()
                }}
              >
                <Video className="h-3.5 w-3.5 mr-1" />
                {hasVideo ? "重新上传视频" : "上传视频"}
              </Button>
              {hasAudio && (
                <Button size="sm" variant="outline" asChild>
                  <a href={asset.audio_url} target="_blank" rel="noreferrer">
                    <Play className="h-3.5 w-3.5 mr-1" />
                    打开音频
                  </a>
                </Button>
              )}
              {hasVideo && (
                <Button size="sm" variant="outline" asChild>
                  <a href={asset.video_url} target="_blank" rel="noreferrer">
                    <Play className="h-3.5 w-3.5 mr-1" />
                    打开视频
                  </a>
                </Button>
              )}
            </div>
          </div>
        </Card>
      )
    }

    const isProcessing = processingIds.has(asset.id)

    return (
      <Card key={asset.id} className="overflow-hidden group">
        <div className="relative aspect-square bg-secondary/30">
          {hasImage ? (
            <img
              src={asset.main_image}
              alt={asset.canonical_name}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <ImageIcon className="h-12 w-12 text-muted-foreground/40" />
            </div>
          )}

          {isProcessing && (
            <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
              <div className="text-center">
                <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto" />
                <p className="text-xs text-white mt-2">生成中...</p>
              </div>
            </div>
          )}

          {!isProcessing && (
            <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => handleGenerate(asset.id)}
              >
                {hasImage ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 mr-1" />
                    重新生成
                  </>
                ) : (
                  "生成主图"
                )}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  uploadRefMain.current?.setAttribute("data-asset-id", String(asset.id))
                  uploadRefMain.current?.click()
                }}
              >
                <Upload className="h-3.5 w-3.5 mr-1" />
                上传主图
              </Button>
            </div>
          )}
        </div>

        <div className="flex gap-1 px-2 pt-2">
          {[asset.angle_image_1, asset.angle_image_2].map((img, idx) => (
            <div
              key={idx}
              className="w-1/2 aspect-video bg-secondary/30 rounded overflow-hidden relative group/sub cursor-pointer"
              onClick={() => {
                const ref = idx === 0 ? uploadRef1 : uploadRef2
                ref.current?.click()
                ref.current?.setAttribute("data-asset-id", String(asset.id))
                ref.current?.setAttribute("data-field", idx === 0 ? "angle_image_1" : "angle_image_2")
              }}
            >
              {img ? (
                <img src={img} alt={`参考图${idx + 1}`} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <Upload className="h-3.5 w-3.5 text-muted-foreground/40" />
                </div>
              )}
              <div className="absolute inset-0 bg-black/50 opacity-0 group-hover/sub:opacity-100 transition-opacity flex items-center justify-center">
                <Upload className="h-4 w-4 text-white" />
              </div>
            </div>
          ))}
        </div>

        <div className="p-3 space-y-2">
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm truncate flex-1">{asset.canonical_name}</span>
            {hasImage && (
              <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
            )}
          </div>
          {asset.description && (
            <p className="text-xs text-muted-foreground line-clamp-1">{asset.description}</p>
          )}
          <div className="flex items-center justify-between">
            <Badge variant="secondary" className="text-xs">
              {asset.aliases?.length ? asset.aliases[0] : ""}
            </Badge>
            <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-primary"
                onClick={() => handleEditOpen(asset)}
              >
                <Pencil className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-destructive"
                onClick={() => handleDelete(asset)}
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">视觉资产</h2>
          <p className="text-muted-foreground mt-1">为提取的实体生成视觉参考图</p>
        </div>
        {missingCount > 0 && (
          <Button onClick={handleBatchGenerate} disabled={batchGenerating}>
            {batchGenerating ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                批量生成中...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4 mr-2" />
                一键生成 ({missingCount})
              </>
            )}
          </Button>
        )}
      </div>

      {/* Hidden file inputs for upload */}
      <input
        ref={uploadRef1}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          const el = e.target
          const assetId = Number(el.getAttribute("data-asset-id"))
          const field = el.getAttribute("data-field") as "angle_image_1" | "angle_image_2"
          if (file && assetId && field) handleUpload(assetId, field, file)
          el.value = ""
        }}
      />
      <input
        ref={uploadRef2}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          const el = e.target
          const assetId = Number(el.getAttribute("data-asset-id"))
          const field = el.getAttribute("data-field") as "angle_image_1" | "angle_image_2"
          if (file && assetId && field) handleUpload(assetId, field, file)
          el.value = ""
        }}
      />
      <input
        ref={uploadRefMain}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          const el = e.target
          const assetId = Number(el.getAttribute("data-asset-id"))
          if (file && assetId) handleUpload(assetId, "main_image", file)
          el.value = ""
        }}
      />
      <input
        ref={uploadRefAudio}
        type="file"
        accept="audio/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          const el = e.target
          const assetId = Number(el.getAttribute("data-asset-id"))
          if (file && assetId) handleUpload(assetId, "audio_url", file)
          el.value = ""
        }}
      />
      <input
        ref={uploadRefVideo}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          const el = e.target
          const assetId = Number(el.getAttribute("data-asset-id"))
          if (file && assetId) handleUpload(assetId, "video_url", file)
          el.value = ""
        }}
      />

      {/* Loading state */}
      {loading ? (
        <div className="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <Card key={i} className="overflow-hidden">
              <Skeleton className="aspect-square w-full" />
              <div className="p-3 space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/3" />
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <div className="space-y-8">
          {sections.map((section) => {
            const Icon = section.icon
            return (
              <div key={section.label}>
                <div className={`flex items-center gap-2 mb-4 pl-3 border-l-4 ${section.color}`}>
                  <Icon className={`h-5 w-5 ${section.textColor}`} />
                  <h3 className="text-lg font-semibold">{section.label}</h3>
                  <Badge variant="secondary" className="ml-1">{section.data.length}</Badge>
                </div>

                {section.data.length === 0 ? (
                  <p className="text-sm text-muted-foreground pl-3">暂无数据</p>
                ) : (
                  <div className="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
                    {section.data.map(renderAssetCard)}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Edit Dialog */}
      <Dialog open={!!editingAsset} onOpenChange={(open) => !open && setEditingAsset(null)}>
        <DialogContent className="glass">
          <DialogHeader>
            <DialogTitle className="gradient-text text-xl">编辑资产</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">名称</label>
              <Input
                value={editForm.canonical_name}
                onChange={(e) => setEditForm((f) => ({ ...f, canonical_name: e.target.value }))}
                placeholder="资产名称"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">别名</label>
              <Input
                value={editForm.aliases}
                onChange={(e) => setEditForm((f) => ({ ...f, aliases: e.target.value }))}
                placeholder="多个别名用逗号分隔"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">描述</label>
              <Textarea
                value={editForm.description}
                onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="详细描述"
                rows={3}
              />
            </div>

            {editingAsset?.asset_type !== AssetTypeEnum.GENERAL && (
              <div className="space-y-2">
                <label className="text-sm font-medium">固有特征 (用于 Prompt)</label>
                <Textarea
                  value={editForm.base_traits}
                  onChange={(e) => setEditForm((f) => ({ ...f, base_traits: e.target.value }))}
                  placeholder="英文特征描述，用于生成参考图"
                  rows={6}
                  className="font-mono text-sm"
                />
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditingAsset(null)} disabled={saving}>
              取消
            </Button>
            <Button
              onClick={handleEditSave}
              disabled={!editForm.canonical_name.trim() || saving}
              className="shadow-lg shadow-primary/20"
            >
              {saving && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
