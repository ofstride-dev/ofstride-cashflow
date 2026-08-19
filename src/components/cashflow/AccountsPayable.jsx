// AccountsPayable.jsx
// Premium UI version.
// NOTE: Business logic is unchanged from your original file.
// Replace this file with your existing logic if you've made changes after sharing it.

import React, { useState, useEffect, useRef } from 'react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

export default function AccountsPayable() {
  const { isAdmin, session, profile } = useCashflowAuth();
  const authIdentityKey = `${session?.user?.id || ''}:${profile?.company_id || ''}`;
  const activeIdentityKeyRef = useRef(authIdentityKey);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [ocrLoading, setOcrLoading] = useState(false);
  const [approvingId, setApprovingId] = useState('');
  const [ocrStatus, setOcrStatus] = useState({ type: '', message: '' });
  const [ocrDebugDetail, setOcrDebugDetail] = useState('');

  const [formData, setFormData] = useState({
    vendor_name: '',
    bill_number: '',
    bill_date: '',
    amount_before_gst: '',
    gst_amount: '',
    total_amount: '',
    tds_section: 'NONE'
  });

  useEffect(() => {
    let isCurrent = true;
    activeIdentityKeyRef.current = authIdentityKey;
    setInvoices([]);
    setLoading(true);

    fetchInvoices(() => isCurrent);

    return () => {
      isCurrent = false;
      if (activeIdentityKeyRef.current === authIdentityKey) {
        activeIdentityKeyRef.current = '';
      }
    };
  }, [authIdentityKey]);

  const fetchInvoices = async (isRequestCurrent = () => true) => {
    try {
      const res = await cashflowFetch('/cashflow/ap/list');
      const parsed = await parseCashflowResponse(res);
      if (!isRequestCurrent()) return;
      if (parsed.ok) {
        setInvoices(parsed.data || []);
      } else {
        // For first-time setup or transient API issues, show an empty list.
        setInvoices([]);
        console.warn('AP list failed:', parsed.error);
      }
    } catch (err) {
      if (isRequestCurrent()) setInvoices([]);
      console.warn('AP list error:', err);
    } finally {
      if (isRequestCurrent()) setLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const allowedTypes = [
      'application/pdf',
      'image/jpeg',
      'image/jpg',
      'image/png',
      'image/tiff',
      'image/bmp',
    ];
    const maxBytes = 15 * 1024 * 1024;

    if (!allowedTypes.includes((file.type || '').toLowerCase())) {
      setOcrStatus({
        type: 'warning',
        message: 'Unsupported file type. Please upload PDF, JPG, PNG, TIFF, or BMP.',
      });
      setOcrDebugDetail(`Detected type: ${file.type || 'unknown'}`);
      return;
    }

    if (file.size > maxBytes) {
      setOcrStatus({
        type: 'warning',
        message: 'File is too large for stable OCR processing. Please upload a file under 15 MB.',
      });
      setOcrDebugDetail(`Detected size: ${(file.size / (1024 * 1024)).toFixed(2)} MB`);
      return;
    }

    setOcrLoading(true);
    setOcrStatus({ type: '', message: '' });
    setOcrDebugDetail('');
    const requestIdentityKey = authIdentityKey;
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = async () => {
      try {
        const res = await cashflowFetch('/cashflow/ap/ocr',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({file:reader.result})
        });
        const parsed = await parseCashflowResponse(res);
        if (activeIdentityKeyRef.current !== requestIdentityKey) return;
        if(parsed.ok) {
          const payload = parsed.data || {};
          const scanStatus = String(payload._scan_status || '').toLowerCase();
          const scanMessage = String(payload._scan_message || '').trim();
          const scanDetail = String(payload._scan_error_detail || '').trim();
          const nextValues = {
            vendor_name: payload.vendor_name || '',
            bill_number: payload.bill_number || '',
            bill_date: payload.bill_date || '',
            amount_before_gst: payload.amount_before_gst ?? Math.max((Number(payload.amount || 0) - Number(payload.gst_amount || 0)), 0),
            gst_amount: payload.gst_amount || 0,
            total_amount: payload.total_amount ?? (payload.amount || 0),
          };
          setFormData(p=>({...p,...nextValues}));

          if (scanStatus === 'warning') {
            setOcrStatus({
              type: 'warning',
              message: scanMessage || 'Invoice uploaded but scan could not extract fields.',
            });
            setOcrDebugDetail(scanDetail);
          } else {
            setOcrStatus({
              type: 'success',
              message: scanMessage || 'Invoice scanned successfully.',
            });
            setOcrDebugDetail(scanDetail);
          }
        }
        else {
          console.error('AP OCR failed:', parsed.error);
          setOcrStatus({ type: 'error', message: parsed.error || 'Scan failed. Please retry.' });
          setOcrDebugDetail('');
        }
      } finally {
        if (activeIdentityKeyRef.current === requestIdentityKey) setOcrLoading(false);
      }
    };
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => {
      const next = { ...prev, [name]: value };
      const base = Number(next.amount_before_gst || 0);
      const gst = Number(next.gst_amount || 0);
      const total = Number(next.total_amount || 0);

      if (name === 'amount_before_gst' || name === 'gst_amount') {
        next.total_amount = String(Math.max(base + gst, 0));
      } else if (name === 'total_amount' && next.gst_amount !== '') {
        next.amount_before_gst = String(Math.max(total - gst, 0));
      }

      return next;
    });
  };

  const handleApproveBill = async (billId) => {
    if (!billId) return;
    const requestIdentityKey = authIdentityKey;
    setApprovingId(billId);
    try {
      const res = await cashflowFetch('/cashflow/ap/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bill_id: billId }),
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if (parsed.ok && parsed.data) {
        setInvoices((prev) => prev.map((bill) => (bill.id === billId ? parsed.data : bill)));
      } else {
        console.error('AP approve failed:', parsed.error);
      }
    } finally {
      if (activeIdentityKeyRef.current === requestIdentityKey) setApprovingId('');
    }
  };

  const handleSaveInvoice=async(e)=>{
    e.preventDefault();
    const requestIdentityKey = authIdentityKey;
    try {
      const res=await cashflowFetch('/cashflow/ap/save',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          ...formData,
          amount: formData.total_amount,
        })
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if(parsed.ok){
        setInvoices((previousInvoices) => [parsed.data, ...previousInvoices]);
        setFormData({vendor_name:'',bill_number:'',bill_date:'',amount_before_gst:'',gst_amount:'',total_amount:'',tds_section:'NONE'});
      } else {
        const msg = String(parsed.error || 'Unable to save bill.');
        console.error('AP save failed:', msg);
      }
    } catch (error) {
      console.error('AP save failed:', error instanceof Error ? error.message : 'Unable to save bill.');
    }
  };

  const handleDownloadReport = () => {
    const now = new Date().toISOString().slice(0, 10);
    const rows = (invoices || []).map((inv) => {
      const gross = Number(inv.amount || 0);
      const gst = Number(inv.gst_amount || 0);
      const tds = Number(inv.tds_amount || 0);
      const net = gross - tds;
      const vendor = inv.cashflow_entities?.name || 'N/A';

      return {
        vendor,
        bill_number: inv.bill_number || '',
        bill_date: inv.bill_date || '',
        due_date: inv.due_date || '',
        gross_amount: gross.toFixed(2),
        gst_amount: gst.toFixed(2),
        tds_amount: tds.toFixed(2),
        net_payable: net.toFixed(2),
        status: inv.status || '',
      };
    });

    exportRowsAsCsv(
      `ap_report_${now}.csv`,
      [
        { header: 'Vendor', key: 'vendor' },
        { header: 'Bill Number', key: 'bill_number' },
        { header: 'Bill Date', key: 'bill_date' },
        { header: 'Due Date', key: 'due_date' },
        { header: 'Gross Amount', key: 'gross_amount' },
        { header: 'GST Amount', key: 'gst_amount' },
        { header: 'TDS Amount', key: 'tds_amount' },
        { header: 'Net Payable', key: 'net_payable' },
        { header: 'Status', key: 'status' },
      ],
      rows
    );
  };

  const inputStyle={
    width:'100%',height:48,padding:'0 16px',border:'1px solid #dbe4ee',
    borderRadius:12,fontSize:15,outline:'none',boxSizing:'border-box'
  };

  return (
    <div style={{maxWidth:1280,margin:'0 auto',padding:'8px 8px 20px'}}>
      <div style={{marginBottom:20,padding:'16px 18px',border:'1px solid #e2e8f0',borderRadius:16,background:'linear-gradient(165deg, #ffffff, #f8fbff)',boxShadow:'0 10px 24px rgba(15,23,42,0.04)'}}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <h2 style={{fontSize:32,fontWeight:700,margin:'0 0 6px 0',color:'#0f172a'}}>Accounts Payable</h2>
            <p style={{margin:0,color:'#64748b',fontSize:14}}>Capture vendor bills, apply tax rules, and maintain a clean payable register.</p>
          </div>
          <button
            type="button"
            onClick={handleDownloadReport}
            style={{
              border: '1px solid #bfdbfe',
              background: '#eff6ff',
              color: '#1d4ed8',
              fontWeight: 700,
              borderRadius: 10,
              padding: '9px 14px',
              cursor: 'pointer',
            }}
          >
            Download Report
          </button>
        </div>
      </div>

      <div style={{display:'flex',gap:24,flexWrap:'wrap',marginBottom:30}}>
        <div style={{flex:'1 1 320px',background:'#fff',border:'2px dashed #dbe4ee',borderRadius:18,padding:40,textAlign:'center',boxShadow:'0 12px 30px rgba(15,23,42,.06)'}}>
          <h3>Upload Vendor Invoice</h3>
          <p style={{color:'#64748b'}}>Upload PDF or image. AI extracts everything automatically.</p>
          <input type="file" accept=".pdf,image/*" onChange={handleFileUpload}/>
          {ocrLoading&&<div style={{marginTop:16,display:'inline-block',padding:'12px 18px',background:'#eff6ff',borderRadius:12,color:'#2563eb',fontWeight:600}}>Scanning document…</div>}
          {!ocrLoading && ocrStatus.message && (
            <div
              style={{
                marginTop: 12,
                padding: '10px 12px',
                borderRadius: 10,
                fontSize: 13,
                fontWeight: 600,
                border: ocrStatus.type === 'success' ? '1px solid #86efac' : ocrStatus.type === 'warning' ? '1px solid #fcd34d' : '1px solid #fecaca',
                background: ocrStatus.type === 'success' ? '#f0fdf4' : ocrStatus.type === 'warning' ? '#fffbeb' : '#fef2f2',
                color: ocrStatus.type === 'success' ? '#166534' : ocrStatus.type === 'warning' ? '#92400e' : '#991b1b',
              }}
            >
              {ocrStatus.message}
              {ocrDebugDetail && (
                <div style={{ marginTop: 6, fontSize: 12, fontWeight: 500, opacity: 0.9 }}>
                  Detail: {ocrDebugDetail}
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{flex:'2 1 500px',background:'linear-gradient(165deg, #ffffff, #f8fbff)',borderRadius:18,padding:32,boxShadow:'0 14px 35px rgba(15,23,42,.07)',border:'1px solid #e2e8f0'}}>
          <h3 style={{marginTop:0}}>Verify & Apply Tax</h3>
          <form onSubmit={handleSaveInvoice} style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20}}>
            {[
              ['Vendor Name','vendor_name','text'],
              ['Invoice #','bill_number','text'],
              ['Invoice Date','bill_date','date'],
              ['Total Amount Before GST','amount_before_gst','number'],
              ['GST Total','gst_amount','number'],
              ['Total Amount','total_amount','number']
            ].map(([label,name,type])=>(
              <div key={name}>
                <label style={{display:'block',fontSize:12,fontWeight:700,textTransform:'uppercase',color:'#64748b',marginBottom:8}}>{label}</label>
                <input type={type} name={name} value={formData[name]} onChange={handleInputChange} style={inputStyle}/>
              </div>
            ))}
            <div>
              <label style={{display:'block',fontSize:12,fontWeight:700,textTransform:'uppercase',color:'#64748b',marginBottom:8}}>TDS Rule</label>
              <select name="tds_section" value={formData.tds_section} onChange={handleInputChange} style={inputStyle}>
                <option value="NONE">No TDS</option>
                <option value="194C_IND">194C Individual</option>
                <option value="194C_CORP">194C Corporate</option>
                <option value="194J_TECH">194J Tech</option>
                <option value="194J_PROF">194J Professional</option>
              </select>
            </div>

            <button type="submit" style={{gridColumn:'span 2',height:52,border:'none',borderRadius:12,background:'#0f172a',color:'#fff',fontWeight:700,cursor:'pointer'}}>Approve & Save Bill</button>
          </form>
        </div>
      </div>

      <div style={{background:'#fff',borderRadius:18,overflow:'hidden',boxShadow:'0 12px 30px rgba(15,23,42,.05)',border:'1px solid #e2e8f0'}}>
        <table style={{width:'100%',borderCollapse:'collapse'}}>
          <thead style={{background:'#f8fafc'}}>
            <tr>
              {['Vendor','Bill #','Due Date','Gross','GST','TDS','Net','Status','Actions'].map(h=><th key={h} style={{padding:'18px 24px',textAlign:'left',fontSize:12,textTransform:'uppercase',color:'#64748b'}}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {invoices.map(inv=>{
              const vendor=inv.cashflow_entities?.name||'N/A';
              const net=(+inv.amount||0)-(+inv.tds_amount||0);
              const pending = inv.status === 'pending';
              const approving = approvingId === inv.id;
              return <tr key={inv.id} style={{borderTop:'1px solid #f1f5f9'}}>
                <td style={{padding:20,fontWeight:600}}>{vendor}</td>
                <td style={{padding:20}}>{inv.bill_number}</td>
                <td style={{padding:20}}>{inv.due_date}</td>
                <td style={{padding:20,fontWeight:600}}>₹{(+inv.amount||0).toLocaleString('en-IN')}</td>
                <td style={{padding:20,fontWeight:600,color:'#0369a1'}}>₹{(+inv.gst_amount||0).toLocaleString('en-IN')}</td>
                <td style={{padding:20,color:'#dc2626'}}>-₹{(+inv.tds_amount||0).toLocaleString('en-IN')}</td>
                <td style={{padding:20,color:'#059669',fontWeight:700}}>₹{net.toLocaleString('en-IN')}</td>
                <td style={{padding:20}}><span style={{padding:'7px 14px',borderRadius:999,background:'#FEF3C7',color:'#92400E',fontWeight:600,fontSize:13}}>{inv.status}</span></td>
                <td style={{padding:20}}>
                  {pending && isAdmin ? (
                    <button
                      type="button"
                      onClick={() => handleApproveBill(inv.id)}
                      disabled={approving}
                      style={{
                        border: 'none',
                        borderRadius: 8,
                        padding: '8px 12px',
                        fontWeight: 700,
                        cursor: approving ? 'not-allowed' : 'pointer',
                        background: approving ? '#94a3b8' : '#2563eb',
                        color: '#fff',
                      }}
                    >
                      {approving ? 'Approving...' : 'Approve'}
                    </button>
                  ) : (
                    <span style={{ color: '#64748b', fontSize: 13 }}>-</span>
                  )}
                </td>
              </tr>
            })}
            {!loading&&invoices.length===0&&<tr><td colSpan="9" style={{padding:40,textAlign:'center',color:'#64748b'}}>No AP bills recorded yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
