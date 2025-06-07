from domino.tags import link, script


class BootstrapCSS(link):
	def inner(self):
		self.configure(href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css", rel="stylesheet")	

class JQuery(script):
	def inner(self):
		self.configure(src="https://code.jquery.com/jquery-3.5.1.slim.min.js")

class PopperJS(script):
	def inner(self):
		self.configure(src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.5.2/dist/umd/popper.min.js")

class BootstrapJS(script):
	def inner(self):
		self.configure(src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js")

class container:
	pass

class container_fluid:
	pass

class row:
	pass

class col:
	pass

class col_1:
	pass

class col_2:
	pass

class col_3:
	pass

class col_4:
	pass

class col_5:
	pass

class col_6:
	pass

class col_7:
	pass

class col_8:
	pass

class col_9:
	pass

class col_10:
	pass

class col_11:
	pass

class col_12:
	pass

class offset_1:
	pass

class offset_2:
	pass

class offset_3:
	pass

class offset_4:
	pass

class offset_5:
	pass

class offset_6:
	pass

class offset_7:
	pass

class offset_8:
	pass

class offset_9:
	pass

class offset_10:
	pass

class offset_11:
	pass

class order_1:
	pass

class order_2:
	pass

class order_3:
	pass

class order_4:
	pass

class order_5:
	pass

class order_6:
	pass

class order_7:
	pass

class order_8:
	pass

class order_9:
	pass

class order_10:
	pass

class order_11:
	pass

class order_12:
	pass

class order_first:
	pass

class order_last:
	pass

class d_none:
	pass

class d_inline:
	pass

class d_inline_block:
	pass

class d_block:
	pass

class d_flex:
	pass

class d_inline_flex:
	pass

class justify_content_start:
	pass

class justify_content_end:
	pass

class justify_content_center:
	pass

class justify_content_between:
	pass

class justify_content_around:
	pass

class align_items_start:
	pass

class align_items_end:
	pass

class align_items_center:
	pass

class align_items_baseline:
	pass

class align_items_stretch:
	pass

class align_self_auto:
	pass

class align_self_start:
	pass

class align_self_end:
	pass

class align_self_center:
	pass

class align_self_baseline:
	pass

class align_self_stretch:
	pass

class flex_1:
	pass

class flex_auto:
	pass

class flex_initial:
	pass

class flex_none:
	pass

class flex_row:
	pass

class flex_row_reverse:
	pass

class flex_column:
	pass

class flex_column_reverse:
	pass

class flex_wrap:
	pass

class flex_wrap_reverse:
	pass

class bg_primary:
	pass

class bg_secondary:
	pass

class bg_success:
	pass

class bg_danger:
	pass

class bg_warning:
	pass

class bg_info:
	pass

class bg_light:
	pass

class bg_dark:
	pass

class bg_white:
	pass

class text_primary:
	pass

class text_secondary:
	pass

class text_success:
	pass

class text_danger:
	pass

class text_warning:
	pass

class text_info:
	pass

class text_light:
	pass

class text_dark:
	pass

class text_muted:
	pass

class text_white:
	pass

class text_center:
	pass

class text_left:
	pass

class text_right:
	pass

class text_nowrap:
	pass

class text_lg:
	pass

class text_sm:
	pass

class text_xl:
	pass

class text_xs:
	pass

class text_capitalize:
	pass

class text_lowercase:
	pass

class text_uppercase:
	pass

class font_weight_bold:
	pass

class font_weight_normal:
	pass

class font_weight_lighter:
	pass

class font_weight_bolder:
	pass

class text_truncate:
	pass

class text_justify:
	pass

class text_break:
	pass

class visible:
	pass

class invisible:
	pass

class sr_only:
	pass

class sr_only_focusable:
	pass

class opacity_0:
	pass

class opacity_25:
	pass

class opacity_50:
	pass

class opacity_75:
	pass

class opacity_100:
	pass

class m_0:
	pass

class m_1:
	pass

class m_2:
	pass

class m_3:
	pass

class m_4:
	pass

class m_5:
	pass

class mt_0:
	pass

class mt_1:
	pass

class mt_2:
	pass

class mt_3:
	pass

class mt_4:
	pass

class mt_5:
	pass

class mb_0:
	pass

class mb_1:
	pass

class mb_2:
	pass

class mb_3:
	pass

class mb_4:
	pass

class mb_5:
	pass

class ml_0:
	pass

class ml_1:
	pass

class ml_2:
	pass

class ml_3:
	pass

class ml_4:
	pass

class ml_5:
	pass

class mr_0:
	pass

class mr_1:
	pass

class mr_2:
	pass

class mr_3:
	pass

class mr_4:
	pass

class mr_5:
	pass

class mx_0:
	pass

class mx_1:
	pass

class mx_2:
	pass

class mx_3:
	pass

class mx_4:
	pass

class mx_5:
	pass

class my_0:
	pass

class my_1:
	pass

class my_2:
	pass

class my_3:
	pass

class my_4:
	pass

class my_5:
	pass

class p_0:
	pass

class p_1:
	pass

class p_2:
	pass

class p_3:
	pass

class p_4:
	pass

class p_5:
	pass

class pt_0:
	pass

class pt_1:
	pass

class pt_2:
	pass

class pt_3:
	pass

class pt_4:
	pass

class pt_5:
	pass

class pb_0:
	pass

class pb_1:
	pass

class pb_2:
	pass

class pb_3:
	pass

class pb_4:
	pass

class pb_5:
	pass

class pl_0:
	pass

class pl_1:
	pass

class pl_2:
	pass

class pl_3:
	pass

class pl_4:
	pass

class pl_5:
	pass

class pr_0:
	pass

class pr_1:
	pass

class pr_2:
	pass

class pr_3:
	pass

class pr_4:
	pass

class pr_5:
	pass

class px_0:
	pass

class px_1:
	pass

class px_2:
	pass

class px_3:
	pass

class px_4:
	pass

class px_5:
	pass

class py_0:
	pass

class py_1:
	pass

class py_2:
	pass

class py_3:
	pass

class py_4:
	pass

class py_5:
	pass
