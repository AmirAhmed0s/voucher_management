frappe.ui.form.on('Vouchers Entry', {
    onload: function(frm) {
        // تنسيق الواجهة
        frappe.dom.set_style(`
            .grid-row[data-fieldname="amount_after_tax"] { background-color: #f0fff4 !important; }
            .btn-view-ledger { background-color: #2d3748 !important; color: white !important; }
        `);
    },

    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('View General Ledger'), function() {
                frappe.set_route("query-report", "General Ledger", {
                    "voucher_no": frm.doc.name,
                    "company": frm.doc.company
                });
            }).addClass('btn-view-ledger');
        }
        apply_custom_filters(frm);
    },

    employee: function(frm) {
        if (frm.doc.employee) {
            frappe.show_alert({message: __("Employee set as Party for Payment Account"), indicator: 'blue'});
        }
    }
});

frappe.ui.form.on('Voucher Entry Account', {
    item: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item) {
            // فرض أن يكون الطرف مورد عند اختيار صنف
            frappe.model.set_value(cdt, cdn, 'party_type', 'Supplier');
            
            // جلب بيانات الصنف
            frappe.db.get_value('Item', row.item, ['item_name', 'standard_rate'], (r) => {
                if (r) {
                    frappe.model.set_value(cdt, cdn, 'user_remark', r.item_name);
                    if (!row.amount) frappe.model.set_value(cdt, cdn, 'amount', r.standard_rate);
                }
            });
        }
    },

    amount: function(frm, cdt, cdn) { calculate_row_totals(frm, cdt, cdn); },
    qty: function(frm, cdt, cdn) { calculate_row_totals(frm, cdt, cdn); },
    taxes: function(frm, cdt, cdn) { calculate_row_totals(frm, cdt, cdn); }
});

// دالة الحسابات الذكية
function calculate_row_totals(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    let total_basic = flt(row.amount) * (flt(row.qty) || 1);
    
    if (row.taxes) {
        frappe.db.get_doc('Purchase Taxes and Charges Template', row.taxes).then(doc => {
            let rate = 0;
            doc.taxes.forEach(t => { rate += flt(t.rate); });
            let tax_val = flt(total_basic * (rate / 100));
            
            frappe.model.set_value(cdt, cdn, {
                'tax_amount': tax_val,
                'amount_before_tax': total_basic,
                'amount_after_tax': total_basic + tax_val
            });
            update_master_totals(frm);
        });
    } else {
        frappe.model.set_value(cdt, cdn, {
            'tax_amount': 0,
            'amount_before_tax': total_basic,
            'amount_after_tax': total_basic
        });
        update_master_totals(frm);
    }
}

function update_master_totals(frm) {
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

function apply_custom_filters(frm) {
    frm.set_query('account_payment', () => {
        return { filters: { 'company': frm.doc.company, 'is_group': 0 } };
    });
}
