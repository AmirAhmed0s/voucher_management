// Copyright (c) 2025, Amir and contributors
// For license information, please see license.txt

// ==========================================
// Global variables for caching and dialog state
// ==========================================
let cached_dimensions = null;
let is_dialog_active = false;

// ==========================================
// Vouchers Entry form events
// ==========================================
frappe.ui.form.on("Vouchers Entry", {
	onload: function (frm) {
		// Load custom accounting dimensions once for performance
		if (!cached_dimensions) {
			frappe.db
				.get_list("Accounting Dimension", {
					fields: ["label", "fieldname", "document_type"],
					filters: { disabled: 0 },
				})
				.then((res) => {
					cached_dimensions = res;
				});
		}
		inject_enhanced_styles();
		apply_vouchers_filters(frm);
	},

	refresh: function (frm) {
		// Add View Ledger button when submitted
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("View Ledger"),
				function () {
					frappe.set_route("query-report", "General Ledger", {
						voucher_no: frm.doc.name,
						company: frm.doc.company,
					});
				},
				__("View")
			);
		}
		refresh_dimension_buttons(frm);
	},

	// Auto-fetch employee's default account when employee is selected
	employee: function (frm) {
		if (frm.doc.employee) {
			frappe.db.get_value(
				"Employee",
				frm.doc.employee,
				"custom_default_employee_account",
				(r) => {
					if (r && r.custom_default_employee_account && !frm.doc.account_payment) {
						frm.set_value("account_payment", r.custom_default_employee_account);
					}
				}
			);
		}
	},
});

// ==========================================
// Voucher Entry Account child table events
// ==========================================
frappe.ui.form.on("Voucher Entry Account", {
	// Clear row fields when a new row is added
	references_add: function (frm, cdt, cdn) {
		setTimeout(() => {
			frappe.model.set_value(cdt, cdn, {
				account: "",
				party_type: "",
				party: "",
				amount: 0,
				amount_before_tax: 0,
				tax_amount: 0,
				amount_after_tax: 0,
				cost_center: "",
				project: "",
				fixed_asset: 0,
				item: "",
				qty: 1,
			});
			// Copy remark from previous row for convenience
			let all_rows = frm.doc.references || [];
			if (all_rows.length > 1) {
				frappe.model.set_value(
					cdt,
					cdn,
					"user_remark",
					all_rows[all_rows.length - 2].user_remark
				);
			}
			frm.refresh_field("references");
		}, 10);
	},

	// Show/hide item and qty fields based on fixed_asset checkbox
	fixed_asset: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.fixed_asset) {
			frappe.model.set_value(cdt, cdn, "item", "");
			frappe.model.set_value(cdt, cdn, "qty", 1);
		}
		frm.refresh_field("references");
	},

	// Fetch item defaults when item is selected
	item: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item) {
			frappe.model.set_value(cdt, cdn, "party_type", "Supplier");
			frappe.db.get_value("Item", row.item, ["item_name", "standard_rate"], (r) => {
				if (r) {
					if (!row.amount) frappe.model.set_value(cdt, cdn, "amount", r.standard_rate);
					if (!row.user_remark)
						frappe.model.set_value(cdt, cdn, "user_remark", r.item_name);
				}
			});
		}
	},

	// Recompute totals when amount, qty, or taxes change
	amount: function (frm, cdt, cdn) {
		compute_row_values(frm, cdt, cdn);
	},
	qty: function (frm, cdt, cdn) {
		compute_row_values(frm, cdt, cdn);
	},
	taxes: function (frm, cdt, cdn) {
		compute_row_values(frm, cdt, cdn);
	},

	// Open dimensions dialog when account is selected
	account: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.account) {
			setTimeout(() => {
				frappe.model.set_value(cdt, cdn, "amount", 0);
				frappe.model.set_value(cdt, cdn, "amount_before_tax", 0);
				frappe.model.set_value(cdt, cdn, "tax_amount", 0);
				frappe.model.set_value(cdt, cdn, "amount_after_tax", 0);
				refresh_dimension_buttons(frm);
				if (!is_dialog_active) open_clean_dimensions_dialog(frm, cdt, cdn);
			}, 100);
		}
	},
});

// ==========================================
// Row computation helper
// ==========================================
function compute_row_values(frm, cdt, cdn) {
	let row = locals[cdt][cdn];
	let qty = flt(row.qty) || 1.0;
	let base_amount = flt(row.amount) * qty;

	if (row.taxes) {
		frappe.db.get_doc("Purchase Taxes and Charges Template", row.taxes).then((doc) => {
			let tax_rate = 0;
			doc.taxes.forEach((t) => {
				tax_rate += flt(t.rate);
			});
			let tax_val = flt(base_amount * (tax_rate / 100));
			frappe.model.set_value(cdt, cdn, {
				tax_amount: tax_val,
				amount_before_tax: base_amount,
				amount_after_tax: base_amount + tax_val,
			});
			refresh_master_totals(frm);
		});
	} else {
		frappe.model.set_value(cdt, cdn, {
			tax_amount: 0,
			amount_before_tax: base_amount,
			amount_after_tax: base_amount,
		});
		refresh_master_totals(frm);
	}
}

function refresh_master_totals(frm) {
	let total = 0,
		tax = 0;
	(frm.doc.references || []).forEach((r) => {
		total += flt(r.amount_before_tax) || flt(r.amount);
		tax += flt(r.tax_amount);
	});
	frm.set_value({
		total_allocated_amount: total,
		total_taxes: tax,
		amount_after_tax: total + tax,
	});
}

function apply_vouchers_filters(frm) {
	frm.set_query("account_payment", () => {
		return { filters: { company: frm.doc.company, is_group: 0 } };
	});
}

// ==========================================
// Dimension edit button (pencil icon) per row
// ==========================================
function refresh_dimension_buttons(frm) {
	if (!frm.fields_dict["references"] || !frm.fields_dict["references"].grid) return;
	frm.fields_dict["references"].grid.wrapper.find(".grid-row").each(function () {
		let n = $(this).attr("data-idx");
		let rows = frm.doc.references || [];
		let row = rows[n - 1];
		let $account_col = $(this).find('[data-fieldname="account"]');
		if (
			row &&
			row.account &&
			$account_col.length &&
			!$account_col.find(".custom-edit-dim").length
		) {
			let $btn = $(
				'<button class="custom-edit-dim btn btn-xs btn-default" title="' +
					__("Edit Dimensions") +
					'" style="margin-left:4px;">✏️</button>'
			);
			$btn.on("click", (e) => {
				e.stopPropagation();
				open_clean_dimensions_dialog(frm, row.doctype, row.name);
			});
			$account_col.append($btn);
		}
	});
}

// ==========================================
// Smart Dimensions Dialog
// ==========================================
function open_clean_dimensions_dialog(frm, cdt, cdn) {
	if (is_dialog_active) return;
	is_dialog_active = true;

	let row = locals[cdt][cdn];

	// Map of display names to fieldnames for standard dimensions
	const standard_field_map = {
		"Cost Center": "cost_center",
		Project: "project",
		Banks: "banks",
		Departments: "departments",
		Debtors: "debtors",
		"Accrues Expenses Types": "accruesexpensestypes",
		"Prepaid Expenses Types": "prepaidexpensestypes",
		"Sales Channel": "saleschannel",
		"Bank Transaction Type": "banktansactiontype",
		"Business Unit": "businessunit",
		Cities: "cities",
		Provinces: "provinces",
		Countries: "countries",
	};

	function get_db_fieldname(display_name) {
		if (standard_field_map[display_name]) return standard_field_map[display_name];
		let found = (cached_dimensions || []).find(
			(d) => d.label === display_name || d.fieldname === display_name
		);
		if (found) return found.fieldname;
		return display_name.toLowerCase().replace(/ /g, "_");
	}

	function get_field_options(fieldname) {
		let found = (cached_dimensions || []).find((d) => d.fieldname === fieldname);
		if (found) return found.document_type;
		if (fieldname === "cost_center") return "Cost Center";
		if (fieldname === "project") return "Project";
		if (fieldname === "countries") return "Country";
		return fieldname;
	}

	// Look up Account Dimension Policy for this account
	let account_filter = row.account;
	frappe.db
		.get_list("Account Dimension Policy", {
			filters: { account: account_filter },
			fields: ["name"],
			limit_page_length: 1,
		})
		.then((list_res) => {
			let policy_promise = Promise.resolve(null);
			if (list_res && list_res.length) {
				policy_promise = frappe.db.get_doc(
					"Account Dimension Policy",
					list_res[0].name
				);
			} else {
				let acct_code = row.account ? row.account.split(" - ")[0] : null;
				if (acct_code) {
					policy_promise = frappe.db
						.get_list("Account Dimension Policy", {
							filters: { account: ["like", acct_code + "%"] },
							fields: ["name"],
							limit_page_length: 1,
						})
						.then((r2) => {
							if (r2 && r2.length)
								return frappe.db.get_doc("Account Dimension Policy", r2[0].name);
							return null;
						});
				}
			}
			return policy_promise;
		})
		.then((policy_doc) => {
			let fields = [];
			let dims_to_render = [];

			if (
				policy_doc &&
				policy_doc.child_dimension &&
				policy_doc.child_dimension.length
			) {
				// Use policy-defined dimensions
				policy_doc.child_dimension.forEach((child) => {
					if (!child.is_visible) return;
					let display_label = child.dimension_name;
					let db_fieldname = get_db_fieldname(display_label);
					let default_val = policy_doc[db_fieldname] || row[db_fieldname] || "";
					dims_to_render.push({
						label: display_label,
						fieldname: db_fieldname,
						options: get_field_options(db_fieldname),
						is_mandatory: child.is_mandatory,
						default_value: default_val,
					});
				});
			} else {
				// Default: show all standard + cached dimensions
				dims_to_render.push({
					label: "Cost Center",
					fieldname: "cost_center",
					options: "Cost Center",
					is_mandatory: false,
					default_value: row.cost_center || "",
				});
				dims_to_render.push({
					label: "Project",
					fieldname: "project",
					options: "Project",
					is_mandatory: false,
					default_value: row.project || "",
				});
				Object.entries(standard_field_map).forEach(([label, fieldname]) => {
					if (fieldname === "cost_center" || fieldname === "project") return;
					dims_to_render.push({
						label: label,
						fieldname: fieldname,
						options: get_field_options(fieldname),
						is_mandatory: false,
						default_value: row[fieldname] || "",
					});
				});
				(cached_dimensions || []).forEach((d) => {
					if (!standard_field_map[d.label]) {
						dims_to_render.push({
							label: d.label,
							fieldname: d.fieldname,
							options: d.document_type,
							is_mandatory: false,
							default_value: row[d.fieldname] || "",
						});
					}
				});
			}

			// Build dialog fields in 3 columns
			dims_to_render.forEach((d, index) => {
				if (index % 3 === 0) fields.push({ fieldtype: "Column Break" });
				fields.push({
					label: __(d.label),
					fieldname: d.fieldname,
					fieldtype: "Link",
					options: d.options,
					default: d.default_value,
					reqd: d.is_mandatory,
					onchange: function () {
						let val = this.get_value();
						frappe.model.set_value(cdt, cdn, d.fieldname, val);
					},
				});
			});

			let row_label =
				(row.account ? row.account.split(" - ")[0] : "") +
				" [" +
				(row.idx || "") +
				"]";
			let dlg = new frappe.ui.Dialog({
				title: __("Accounting Dimensions: {0}", [row_label]),
				fields: fields.length
					? fields
					: [
							{
								fieldtype: "HTML",
								options: "<p>" + __("No accounting dimensions for this account.") + "</p>",
							},
					  ],
				primary_action_label: __("Save & Close"),
				primary_action: function () {
					// Validate mandatory fields
					let missing = [];
					dims_to_render.forEach((dim) => {
						if (dim.is_mandatory && !dlg.get_value(dim.fieldname)) {
							missing.push(dim.label);
						}
					});
					if (missing.length > 0) {
						frappe.msgprint({
							title: __("Required Fields"),
							message:
								__("Please fill in: ") + missing.join(", "),
							indicator: "red",
						});
						return;
					}
					// Save all values
					dims_to_render.forEach((dim) => {
						frappe.model.set_value(cdt, cdn, dim.fieldname, dlg.get_value(dim.fieldname));
					});
					frm.refresh_field("references");
					dlg.hide();
				},
			});

			dlg.on_hide = function () {
				is_dialog_active = false;
				setTimeout(() => {
					let grid_row = frm.fields_dict["references"].grid.get_row(cdn);
					if (grid_row) grid_row.$wrapper.find("input").first().focus();
				}, 200);
			};

			dlg.show();
			dlg.$wrapper.find(".modal-dialog").css("max-width", "900px");
		})
		.catch((err) => {
			// eslint-disable-next-line no-console
			console.error("Error fetching Account Dimension Policy", err);
			is_dialog_active = false;
			frappe.msgprint(__("Error loading dimension settings."));
		});
}

// ==========================================
// CSS styles injection
// ==========================================
function inject_enhanced_styles() {
	if ($("#voucher-mgmt-css").length) return;
	$("head").append(`
		<style id="voucher-mgmt-css">
			/* Highlight fixed asset rows */
			.grid-row[data-fixed_asset="1"] {
				background-color: #fff8e1 !important;
			}
			/* Totals section styling */
			[data-fieldname="amount_after_tax"] .control-value {
				font-weight: bold;
				color: #1a6b3e;
				font-size: 1.1em;
			}
			/* Edit dimension button */
			.custom-edit-dim {
				padding: 1px 4px;
				font-size: 11px;
				line-height: 1;
			}
			/* Payment account highlight */
			[data-fieldname="account_payment"] .control-input input {
				border-left: 3px solid #4c73b3;
			}
		</style>
	`);
}

