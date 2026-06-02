import { useEffect, useMemo, useRef, useState } from 'react'
import { Palette, Plus, Edit3, Trash2, Copy, Image as ImageIcon, Upload, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { api } from '@/services/api'
import type { StyleBinding, StylePreset } from '@/types'

export const BUILTIN_STYLES: StylePreset[] = [
  {
    id: 'builtin-reference-default',
    name: '参考图默认风格',
    positive_prompt:
      '二次元电影感静帧、4K 高保真。角色偏三视图与一致性设计，物品强调多角度材质细节，场景强调广角空间、层次光影与电影构图。',
    source: 'builtin',
    builtin_key: 'reference-default',
  },
]

const STORYBOARD_DEFAULT_FALLBACK: StylePreset = {
  id: 'storyboard-default',
  name: '分镜默认风格',
  positive_prompt:
    'You are an elite Cinematographer (DP) and Sora 2 Prompt Engineering Expert.\n动画摄影指导风格摘要：二维平涂卡通质感，简单镜头语言与扁平化构图，强调角色为中心、剧情信息清晰传递、明快柔和色调，黑体白色描边字幕、卡通化特效文字，沙雕搞笑荒诞氛围、短视频动画节奏',
  source: 'builtin',
  builtin_key: 'storyboard-default',
}

type StyleForm = {
  id?: string
  name: string
  positive_prompt: string
  reference_image: string
}

const emptyForm: StyleForm = {
  name: '',
  positive_prompt: '',
  reference_image: '',
}

export function toStyleBinding(style?: StylePreset | null): StyleBinding | undefined {
  if (!style) return undefined
  return {
    id: style.id,
    name: style.name,
    source: style.source,
    builtin_key: style.builtin_key,
    positive_prompt: style.positive_prompt,
    reference_image: style.reference_image,
  }
}

export async function getAllStylePresets(): Promise<StylePreset[]> {
  const res = await api.getStylePresets(1, 100)
  return [...BUILTIN_STYLES, ...res.data.items]
}

export const StylesPage = () => {
  const [localStyles, setLocalStyles] = useState<StylePreset[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState<StyleForm>(emptyForm)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const uploadRef = useRef<HTMLInputElement>(null)

  const loadStyles = async () => {
    try {
      setLoading(true)
      const res = await api.getStylePresets(1, 100)
      setLocalStyles(res.data.items)
    } catch (err) {
      toast.error((err as Error).message || '加载风格失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadStyles()
  }, [])

  const styles = useMemo(() => {
    const hasStoryboardDefault = localStyles.some((style) => style.builtin_key === 'storyboard-default')
    return [...BUILTIN_STYLES, ...(hasStoryboardDefault ? localStyles : [STORYBOARD_DEFAULT_FALLBACK, ...localStyles])]
  }, [localStyles])

  const openCreate = () => {
    setForm(emptyForm)
    setDialogOpen(true)
  }

  const openEdit = (style: StylePreset) => {
    setForm({
      id: style.id,
      name: style.name,
      positive_prompt: style.positive_prompt,
      reference_image: style.reference_image || '',
    })
    setDialogOpen(true)
  }

  const closeDialog = () => {
    if (uploading || saving) return
    setDialogOpen(false)
    setForm(emptyForm)
  }

  const handleSave = async () => {
    const name = form.name.trim()
    const positivePrompt = form.positive_prompt.trim()
    const referenceImage = form.reference_image.trim()

    if (!name || !positivePrompt) {
      toast.error('请填写风格名称和正向提示词')
      return
    }

    try {
      setSaving(true)
      if (form.id) {
        const res = await api.updateStylePreset(form.id, {
          name,
          positive_prompt: positivePrompt,
          reference_image: referenceImage || undefined,
        })
        setLocalStyles((prev) => {
          const matchIndex = prev.findIndex(
            (item) => item.id === form.id || item.builtin_key === res.data.builtin_key,
          )
          if (matchIndex === -1) {
            return [res.data, ...prev]
          }
          return prev.map((item, index) => (index === matchIndex ? res.data : item))
        })
      } else {
        const res = await api.createStylePreset({
          name,
          positive_prompt: positivePrompt,
          reference_image: referenceImage || undefined,
        })
        setLocalStyles((prev) => [res.data, ...prev])
      }

      toast.success(form.id ? '风格已更新' : '风格已新增')
      setDialogOpen(false)
      setForm(emptyForm)
    } catch (err) {
      toast.error((err as Error).message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (style: StylePreset) => {
    if (style.source !== 'custom') return
    if (!window.confirm(`确定删除「${style.name}」吗？`)) return
    try {
      await api.deleteStylePreset(style.id)
      setLocalStyles((prev) => prev.filter((item) => item.id !== style.id))
      toast.success('风格已删除')
    } catch (err) {
      toast.error((err as Error).message || '删除失败')
    }
  }

  const handleCopyPrompt = async (prompt: string) => {
    try {
      await navigator.clipboard.writeText(prompt)
      toast.success('提示词已复制')
    } catch {
      toast.error('复制失败，请手动复制')
    }
  }

  const handleUploadClick = () => {
    uploadRef.current?.click()
  }

  const handleUploadFile = async (file?: File) => {
    if (!file) return
    try {
      setUploading(true)
      const res = await api.uploadFiles([file])
      const uploaded = res.data.files[0]
      if (!uploaded?.filename) throw new Error('上传结果无文件名')
      setForm((prev) => ({ ...prev, reference_image: `/media/${uploaded.filename}` }))
      toast.success('参考图已上传')
    } catch (err) {
      toast.error((err as Error).message || '上传失败')
    } finally {
      setUploading(false)
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="animate-fade-up flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <div className="relative">
              <Palette className="h-8 w-8 text-primary" />
              <div className="absolute inset-0 blur-lg bg-primary/30 rounded-full" />
            </div>
            <span className="gradient-text">风格管理</span>
          </h1>
          <p className="text-muted-foreground mt-1.5 text-sm">管理前端可见的默认风格与后端持久化的自定义风格。</p>
        </div>
        <Button onClick={openCreate} className="shadow-lg shadow-primary/20">
          <Plus className="mr-2 h-4 w-4" />
          新增风格
        </Button>
      </div>

      <div className="decorative-line animate-fade-in" style={{ animationDelay: '150ms' }} />

      <div className="grid gap-3 md:grid-cols-3">
        <Card className="p-4 bg-card/40 border-border/50">
          <p className="text-sm font-medium">默认风格说明</p>
          <p className="text-sm text-muted-foreground mt-2">默认风格来自工程内置提示词摘录，仅展示适合 UI 阅读的摘要。</p>
        </Card>
        <Card className="p-4 bg-card/40 border-border/50">
          <p className="text-sm font-medium">自定义风格存储</p>
          <p className="text-sm text-muted-foreground mt-2">自定义风格会保存到后端数据库，可被不同页面统一读取。</p>
        </Card>
        <Card className="p-4 bg-card/40 border-border/50">
          <p className="text-sm font-medium">当前影响范围</p>
          <p className="text-sm text-muted-foreground mt-2">本页修改会影响项目风格选择入口，并作为后续生成流程可复用的风格来源。</p>
        </Card>
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground">加载中...</div>
      ) : (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {styles.map((style) => {
          const isBuiltin = style.source === 'builtin'
          const isStoryboardDefault = style.builtin_key === 'storyboard-default'
          const isEditable = !isBuiltin || isStoryboardDefault

          return (
            <Card
              key={style.id}
              className="group overflow-hidden border-border/50 bg-card/40 hover:bg-card/80 hover:border-primary/20 transition-all duration-200"
            >
              <div className="aspect-[16/9] bg-secondary/30 border-b border-border/50">
                {style.reference_image ? (
                  <img src={style.reference_image} alt={style.name} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                    <ImageIcon className="h-10 w-10 opacity-40" />
                    <span className="text-sm">暂无参考图</span>
                  </div>
                )}
              </div>

              <div className="p-5 space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-lg leading-none truncate">{style.name}</h3>
                      {isBuiltin ? (
                        <>
                          <Badge variant="default">默认</Badge>
                          <Badge variant="secondary">内置</Badge>
                        </>
                      ) : (
                        <Badge variant="outline">自定义</Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">
                      {isStoryboardDefault
                        ? '系统默认分镜风格，后端持久化保存，可随时编辑并影响后续分镜生成。'
                        : isBuiltin
                          ? '工程内置提示词摘要，只读展示。'
                          : '后端持久化保存，可编辑和删除。'}
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">正向提示词</p>
                  <div className="rounded-md border bg-background/40 p-3 text-sm leading-6 whitespace-pre-wrap text-foreground/90 min-h-[132px]">
                    {style.positive_prompt}
                  </div>
                </div>

                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <Button variant="outline" size="sm" onClick={() => handleCopyPrompt(style.positive_prompt)}>
                    <Copy className="mr-2 h-4 w-4" />
                    复制提示词
                  </Button>

                  <div className="flex items-center gap-2">
                    {isEditable && (
                      <Button variant="outline" size="sm" onClick={() => openEdit(style)}>
                        <Edit3 className="mr-2 h-4 w-4" />
                        编辑
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      className={isBuiltin ? 'opacity-60 cursor-not-allowed' : 'text-red-500 hover:text-red-400 border-red-500/20 hover:bg-red-500/10'}
                      onClick={() => handleDelete(style)}
                      disabled={isBuiltin}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      删除
                    </Button>
                  </div>
                </div>
              </div>
            </Card>
          )
        })}
      </div>
      )}

      <input
        ref={uploadRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => handleUploadFile(e.target.files?.[0])}
      />

      <Dialog open={dialogOpen} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="glass max-w-2xl">
          <DialogHeader>
            <DialogTitle className="gradient-text text-xl">{form.id ? '编辑风格' : '新增风格'}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">风格名称</label>
              <Input
                value={form.name}
                onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="例如：柔光电影感角色风格"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">正向提示词</label>
              <Textarea
                value={form.positive_prompt}
                onChange={(e) => setForm((prev) => ({ ...prev, positive_prompt: e.target.value }))}
                placeholder="填写该风格的正向提示词"
                rows={8}
                className="font-mono text-sm"
              />
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <label className="text-sm font-medium">参考图</label>
                <Button variant="outline" size="sm" onClick={handleUploadClick} disabled={uploading}>
                  {uploading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      上传中...
                    </>
                  ) : (
                    <>
                      <Upload className="mr-2 h-4 w-4" />
                      上传图片
                    </>
                  )}
                </Button>
              </div>

              <Input
                value={form.reference_image}
                onChange={(e) => setForm((prev) => ({ ...prev, reference_image: e.target.value }))}
                placeholder="可直接填写图片 URL，或上传后自动回填 /media/{filename}"
              />

              <div className="aspect-[16/9] rounded-lg border bg-secondary/30 overflow-hidden">
                {form.reference_image.trim() ? (
                  <img
                    src={form.reference_image.trim()}
                    alt="参考图预览"
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex flex-col items-center justify-center text-muted-foreground gap-2">
                    <ImageIcon className="h-10 w-10 opacity-40" />
                    <span className="text-sm">暂无参考图</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeDialog} disabled={saving || uploading}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving || uploading || !form.name.trim() || !form.positive_prompt.trim()} className="shadow-lg shadow-primary/20">
              {form.id ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
