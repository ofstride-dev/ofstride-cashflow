import { cashflowFetch } from './cashflowApi';

export async function uploadTallyFile(file) {
  const reader = new FileReader();
  const fileContentBase64 = await new Promise((resolve, reject) => {
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',')[1] : value);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  return cashflowFetch('/tally-sync/import', {
    method: 'POST',
    body: JSON.stringify({ file_name: file.name, file_content_base64: fileContentBase64 }),
  });
}

export function downloadTallyExport(kind) {
  return cashflowFetch(`/tally-sync/export?kind=${encodeURIComponent(kind)}`);
}
