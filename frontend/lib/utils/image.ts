/** 浏览器端图片处理：读文件 → 等比压到长边 ≤1600 → data URL（前端约定：上传前先压缩）。 */

export type ResizedImage = {
  /** 可直接用作 <img src> 与 base64 上传的 data URL */
  dataUrl: string;
  /** 处理后图像的尺寸（裁切框坐标空间与后端一致） */
  width: number;
  height: number;
};

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片无法解码"));
    img.src = url;
  });
}

export async function fileToResizedDataUrl(file: File, maxEdge = 1600): Promise<ResizedImage> {
  const original = await readFileAsDataUrl(file);
  const img = await loadImage(original);

  let width = img.naturalWidth;
  let height = img.naturalHeight;
  let dataUrl = original;

  const longest = Math.max(width, height);
  if (longest > maxEdge) {
    const scale = maxEdge / longest;
    width = Math.max(1, Math.round(width * scale));
    height = Math.max(1, Math.round(height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("当前浏览器不支持 canvas");
    ctx.drawImage(img, 0, 0, width, height);
    dataUrl = canvas.toDataURL("image/jpeg", 0.92);
  }

  return { dataUrl, width, height };
}

/** 从粘贴/拖拽事件里取图片文件（没有则返回 null） */
export function pickImageFile(files: FileList | File[] | null | undefined): File | null {
  if (!files || files.length === 0) return null;
  const file = Array.from(files).find((item) => item.type.startsWith("image/"));
  return file ?? null;
}

export function isImageFile(file: File | null | undefined): boolean {
  return Boolean(file && file.type.startsWith("image/"));
}
