frappe.ui.form.on('Vouchers Entry', {
    onload: function(frm) {
        // تحسين مظهر الواجهة
        frappe.dom.set_style(`
            .btn-view-ledger { background-color: #1a202c !important; color: white !important; font-weight: bold; }
            .grid-row[data-fieldname="amount_after_tax"] { background-color: #f7fafc; }
        `);
        apply_vouchers_filters(frm);
    },

    refresh: function(frm) {
        // إذا كان المستند مرحلاً، أضف زر الأستاذ العام
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('View Ledger'), function() {
                frappe.set_route("query-report", "General Ledger", {
                    "voucher_no": frm.doc.name,
                    "company": frm.doc.company
                });
            }, __("View")).addClass('btn-view-ledger');
        }
    }
});

frappe.ui.form.on('Voucher Entry Account', {
    // عند اختيار الصنف
    item: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item) {
            // فرض المورد كطرف تلقائياً
            frappe.model.set_value(cdt, cdn, 'party_type', 'Supplier');
            
            // جلب السعر الافتراضي والاسم
            frappe.db.get_value('Item', row.item, ['item_name', 'standard_rate'], (r) => {
                if (r) {
                    if (!row.amount) frappe.model.set_value(cdt, cdn, 'amount', r.standard_rate);
                    if (!row.user_remark) frappe.model.set_value(cdt, cdn, 'user_remark', r.item_name);
                }
            });
        }
    },

    // إعادة الحساب عند تغيير الكمية أو السعر أو الضريبة
    amount: function(frm, cdt, cdn) { compute_row_values(frm, cdt, cdn); },
    qty: function(frm, cdt, cdn) { compute_row_values(frm, cdt, cdn); },
    taxes: function(frm, cdt, cdn) { compute_row_values(frm, cdt, cdn); }
});

function compute_row_values(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    let qty = flt(row.qty) || 1.0;
    let base_amount = flt(row.amount) * qty;
    
    if (row.taxes) {
        frappe.db.get_doc('Purchase Taxes and Charges Template', row.taxes).then(doc => {
            let tax_rate = 0;
            doc.taxes.forEach(t => { tax_rate += flt(t.rate); });
            let tax_val = flt(base_amount * (tax_rate / 100));
            
            frappe.model.set_value(cdt, cdn, {
                'tax_amount': tax_val,
                'amount_before_tax': base_amount,
                'amount_after_tax': base_amount + tax_val
            });
            refresh_master_totals(frm);
        });
    } else {
        frappe.model.set_value(cdt, cdn, {
            'tax_amount': 0,
            'amount_before_tax': base_amount,
            'amount_after_tax': base_amount
        });
        refresh_master_totals(frm);
    }
}

function refresh_master_totals(frm) {
    let total = 0, tax = 0;
    (frm.doc.references || []).forEach(r => {
        total += flt(r.amount_before_tax);
        tax += flt(r.tax_amount);
    });
    frm.set_value({
        'total_allocated_amount': total,
        'total_taxes': tax,
        'amount_after_tax': total + tax
    });
}

function apply_vouchers_filters(frm) {
    frm.set_query('account_payment', () => {
        return { filters: { 'company': frm.doc.company, 'is_group': 0 } };
    });
}
