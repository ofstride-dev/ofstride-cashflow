import { supabase } from "./supabase";

const MAX_IMAGE_DIMENSION = 1600;
const TARGET_MAX_BYTES = 250 * 1024;
const SIGNED_URL_EXPIRY_SECONDS = 60 * 60 * 24; // 24 hours

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = (err) => {
      URL.revokeObjectURL(url);
      reject(err);
    };
    img.src = url;
  });
}

function canvasToBlob(canvas: HTMLCanvasElement, quality: number, type = "image/jpeg"): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("Failed to compress image"));
        }
      },
      type,
      quality
    );
  });
}

function sanitizeFileName(name: string): string {
  return String(name || "receipt").replace(/[^a-zA-Z0-9._-]/g, "_");
}

// Resizes and re-encodes images as JPEG (~150-250KB target). PNGs with
// transparency are flattened onto a white background so they don't get a black
// background when converted to JPEG. PDFs and other non-image files are
// returned unchanged since they can't be compressed this way.
async function compressImageIfNeeded(file: File): Promise<{ blob: Blob; fileName: string }> {
  if (!file.type || !file.type.startsWith("image/")) {
    return { blob: file, fileName: file.name };
  }

  const img = await loadImage(file);
  let width = img.naturalWidth || img.width;
  let height = img.naturalHeight || img.height;
  if (width > MAX_IMAGE_DIMENSION || height > MAX_IMAGE_DIMENSION) {
    const scale = MAX_IMAGE_DIMENSION / Math.max(width, height);
    width = Math.round(width * scale);
    height = Math.round(height * scale);
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return { blob: file, fileName: file.name };
  }

  // Flatten transparency onto white so JPEG conversion doesn't produce black.
  if (file.type === "image/png") {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
  }
  ctx.drawImage(img, 0, 0, width, height);

  let quality = 0.8;
  let blob = await canvasToBlob(canvas, quality);
  while (blob.size > TARGET_MAX_BYTES && quality > 0.4) {
    quality -= 0.1;
    blob = await canvasToBlob(canvas, quality);
  }

  const baseName = file.name.replace(/\.[^/.]+$/, "");
  return { blob, fileName: `${baseName}.jpg` };
}

export async function uploadReceipt(file: File, userId: string, expenseId: string) {
  const { blob, fileName } = await compressImageIfNeeded(file);
  const safeName = sanitizeFileName(fileName);
  const path = `${userId}/${expenseId}/${Date.now()}_${safeName}`;

  const { error: uploadError } = await supabase.storage
    .from("receipts")
    .upload(path, blob, { contentType: blob.type || file.type });
  if (uploadError) {
    throw uploadError;
  }

  const { data, error: insertError } = await supabase
    .from("expense_attachments")
    .insert({
      expense_id: expenseId,
      storage_path: path,
      file_name: fileName,
      uploaded_at: new Date().toISOString(),
    })
    .select()
    .single();

  // If the DB row fails to insert, remove the orphaned Storage object so we
  // don't leak files that have no DB reference.
  if (insertError) {
    await supabase.storage.from("receipts").remove([path]);
    throw insertError;
  }
  return data;
}

export async function listAttachments(expenseId: string) {
  const { data, error } = await supabase
    .from("expense_attachments")
    .select("*")
    .eq("expense_id", expenseId)
    .order("uploaded_at", { ascending: true });
  if (error) {
    throw error;
  }
  return data || [];
}

export async function getSignedUrl(storagePath: string) {
  const { data, error } = await supabase.storage
    .from("receipts")
    .createSignedUrl(storagePath, SIGNED_URL_EXPIRY_SECONDS);
  if (error) {
    throw error;
  }
  return data?.signedUrl || null;
}