"""订单加入完整计划表：只追加已确认的行；重试去重，冲突不覆盖。"""
import copy
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
from openpyxl.utils.cell import get_column_letter,coordinate_to_tuple
from .production import plan_rows,parts_rows,home_rows,packaging_rows,DATE_COLUMNS,NUMBER_COLUMNS
from .domain import demand,fmt
from .planbook import edit_cell
from .plan_layout import cell_entry,anchor_cell

TARGETS=['最新','整体配件汇总','家用机订单','包材交期跟进','包材资料未确定','采购回复配件到料','出货计划']
DEFAULT_TARGETS=['最新','包材资料未确定']
MASTER_FIELDS={'订单号','产品型号','公司型号','型号','物料编码','物料代码','产品要求','规格型号','规格','类别','产品大类',
               '订单数量','接单日期','受订日期','生产单交期','计划完成日期','产品交期','交期','分析时间'}


def normalized(value):return ''.join(str(value or '').split())


def headers(sheet):
    best={};headrow=1
    for row in range(1,min(sheet['rows'],6)+1):
        found={normalized(sheet['cells'].get(f'{get_column_letter(c)}{row}',{}).get('v')):c for c in range(1,sheet['cols']+1)}
        if '订单号' in found and len(found)>len(best):best=found;headrow=row
    return best,headrow


def equivalent(a,b):
    if a in (None,'') and b in (None,''):return True
    try:return Decimal(str(a))==Decimal(str(b))
    except InvalidOperation:return normalized(a)==normalized(b)


def locate(sheet,columns,headrow,values):
    no_col=columns.get('订单号');model_col=next((columns.get(c) for c in ['产品型号','公司型号','型号','规格型号','规格'] if columns.get(c)),None)
    no=values.get('订单号');model=next((values.get(c) for c in ['产品型号','公司型号','型号','规格型号','规格'] if values.get(c)),None)
    code_col=columns.get('物料编码') or columns.get('物料代码');code=values.get('物料编码') or values.get('物料代码')
    carried='';matches=[]
    for row in range(headrow+1,sheet['rows']+1):
        value=cell_entry(sheet,f'{get_column_letter(no_col)}{row}').get('v') if no_col else None
        if value:carried=str(value)
        existing=cell_entry(sheet,f'{get_column_letter(model_col)}{row}').get('v') if model_col else None
        existing_code=cell_entry(sheet,f'{get_column_letter(code_col)}{row}').get('v') if code_col else None
        if str(carried)==str(no) and ((model and normalized(existing)==normalized(model)) or (not existing and code and normalized(existing_code)==normalized(code))):matches.append(row)
    return matches


def build_preview(payload,orders,targets=None):
    sheets={s['name']:s for s in payload['sheets']} if payload else {}
    result=[]
    for order in orders:
        selected=targets if targets is not None else order.get('plan_targets',DEFAULT_TARGETS)
        for index,item in enumerate(order['items']):
            single=copy.deepcopy(order);single['items']=[item]
            for target in selected:
                masters=MASTER_FIELDS | ({'数量'} if target=='家用机订单' else set())
                if target=='包材资料未确定' and (item.get('packaging') or item.get('completed')):continue
                key=f"{order['id']}:{item['id']}:{target}"
                values={};missing=[]
                if target=='最新':
                    values=plan_rows(single,order.get('plan_serial',''))[0][0]
                    values['分析时间']=item.get('analysis_at','') if item.get('analyzed') else ''
                elif target=='整体配件汇总':values=parts_rows(single)[0]
                elif target=='家用机订单':values=home_rows(single)[0]
                elif target=='包材资料未确定':values=packaging_rows(single)[0]
                elif target=='包材交期跟进':
                    values={'计划序列号':order.get('plan_serial',''),'客订编号':order.get('customer_no',''),'业务员':order.get('owner',''),
                        '订单号':order['number'],'物料编码':item.get('material_code',''),'类别':item.get('category',''),
                        '产品型号':item['model'],'订单数量':item['quantity'],'下单时间':'','按照15日交期推算':'','备注':order.get('notes','')}
                elif target=='采购回复配件到料':
                    values={'客户编号':order.get('customer_no',''),'业务员':order.get('owner',''),'订单号':order['number'],
                        '物料编码':item.get('material_code',''),'类别':item.get('category',''),'规格型号':item.get('requirement') or item['model'],
                        '采购数量':'','下请购单日期':'','采购员':'','到料时间':''}
                elif target=='出货计划':
                    values={'发柜数量':'','订单号':order['number'],'业务员':order.get('owner',''),'型号':item['model'],
                        '数量':'','毛重kg':'','总毛重kg':'','备注说明':order.get('notes',''),'物料情况':'','完成时间':'','危包资料':'','备注':''}
                values.update(order.get('plan_overrides',{}).get(key,{}))
                required={'包材交期跟进':['下单时间'],'采购回复配件到料':['采购数量','下请购单日期','采购员'],
                          '出货计划':['发柜数量','数量','毛重kg']}.get(target,[])
                for field in required:
                    if values.get(field) in ('',None):missing.append(field)
                for field,value in list(values.items()):
                    if value in ('',None):continue
                    if field in NUMBER_COLUMNS or field in ('采购数量','毛重kg','总毛重kg'):
                        try:
                            n=Decimal(str(value))
                            if not n.is_finite() or n<0 or n>Decimal('1e12') or (field in required and n<=0):raise ValueError()
                            values[field]=int(n) if n==int(n) else float(n)
                        except (InvalidOperation,ValueError):missing.append(field+'须为有效非负数量')
                    # 配件汇总的月份是“5月”等文字，家用机表的月份才使用完整日期。
                    if (field in DATE_COLUMNS or field in ('下单时间','下请购单日期')) and not (target=='整体配件汇总' and field=='月份'):
                        try:date.fromisoformat(str(value)[:10])
                        except ValueError:missing.append(field+'须为 YYYY-MM-DD')
                if target=='出货计划' and not missing:values['总毛重kg']=float(Decimal(str(values['数量']))*Decimal(str(values['毛重kg'])))
                if target=='包材交期跟进' and not missing:
                    values['按照15日交期推算']=(date.fromisoformat(str(values['下单时间'])[:10])+timedelta(days=15)).isoformat()
                state='新增';reason='';row=None
                sheet=sheets.get(target)
                cols,headrow=headers(sheet) if sheet else ({},0)
                linked=next((link for link in (payload or {}).get('order_links',[]) if link['order_id']==order['id'] and link['item_id']==item['id'] and link['sheet']==target),None)
                if not sheet:state='暂不能加入';reason='请先导入含此工作表的计划总表'
                elif '订单号' not in cols:state='暂不能加入';reason='未识别到订单号表头'
                elif not any(normalized(n) in cols for n in ('产品型号','公司型号','型号','规格型号','规格')):state='暂不能加入';reason='未识别到型号或规格表头'
                elif missing:state='暂不能加入';reason='待补充：'+'、'.join(dict.fromkeys(missing))
                else:
                    matches=[linked['row']] if linked and linked['row']<=sheet['rows'] else locate(sheet,cols,headrow,values)
                    if len(matches)>1:state='需核对';reason='存在多条相同订单和型号，需人工核对'
                    elif matches:
                        row=matches[0];state='已存在';reason='已存在，不重复加入'
                        for name in ['订单数量','数量','采购数量','物料编码','物料代码']:
                            if normalized(name) not in cols or values.get(name) in ('',None):continue
                            old=cell_entry(sheet,f'{get_column_letter(cols[normalized(name)])}{row}').get('v')
                            if old not in ('',None) and not equivalent(old,values[name]):state='需核对';reason=f'{name}与计划表现有内容不一致，不覆盖';break
                        if linked:
                            differences=[]
                            for name,value in values.items():
                                col=cols.get(normalized(name))
                                if not col or name not in masters or value in ('',None):continue
                                entry=cell_entry(sheet,f'{get_column_letter(col)}{row}')
                                if 'f' not in entry and entry.get('v') not in ('',None) and not equivalent(str(entry['v'])[:10] if entry.get('date') else entry['v'],value):differences.append(name)
                            if differences:state='待更新关联行';reason='关联订单已变化，请核对后勾选更新：'+'、'.join(differences)
                        if state=='已存在':
                            for field,value in values.items():
                                col=cols.get(normalized(field))
                                if col and value not in ('',None):
                                    existing=cell_entry(sheet,f'{get_column_letter(col)}{row}')
                                    if existing.get('v') in ('',None) and 'f' not in existing:
                                        state='补充空白';reason='仅补充现有行的空白格';break
                # 对主表允许先登记，缺失的资料另列待办。
                gaps=[name for name in ('物料编码','类别') if name in values and not values[name]]
                if row is not None:
                    gaps=[name for name in gaps if not cell_entry(sheet,f'{get_column_letter(cols[normalized(name)])}{row}').get('v')] if all(normalized(n) in cols for n in gaps) else gaps
                result.append(dict(key=key,order_id=order['id'],number=order['number'],item_id=item['id'],model=item['model'],
                    sheet=target,values=values,state=state,reason=reason,gaps=gaps,row=row))
    return result


def apply_preview(payload,orders,targets,approved_keys):
    """对确认时的最新数据重算；调用者在同一事务内保存订单和计划表。"""
    updated=copy.deepcopy(payload);saved=copy.deepcopy(orders)
    preview=build_preview(updated,saved,targets);pending={o['id']:[] for o in saved};count=0
    sheets={s['name']:s for s in updated['sheets']} if updated else {}
    for row in preview:
        masters=MASTER_FIELDS | ({'数量'} if row['sheet']=='家用机订单' else set())
        reason=row['reason'];state=row['state']
        if state in ('新增','补充空白','待更新关联行') and row['key'] in approved_keys:
            sheet=sheets[row['sheet']];cols,_=headers(sheet);r=row['row'] if state in ('补充空白','待更新关联行') else sheet['rows']+1
            for field,value in row['values'].items():
                c=cols.get(normalized(field))
                if not c or value in ('',None):continue
                ar,ac=anchor_cell(sheet,r,c);address=f'{get_column_letter(ac)}{ar}'
                if state in ('补充空白','待更新关联行'):
                    original=sheet['cells'].get(address,{})
                    if 'f' in original:continue
                    if original.get('v') not in ('',None) and (state=='补充空白' or field not in masters):continue
                # 借用相邻原表行的样式（不复制公式和数值）。
                above=sheet['cells'].get(f'{get_column_letter(ac)}{ar-1}',{})
                sheet['cells'][address]={'s':sheet['cells'].get(address,above).get('s',0),'date':False}
                if field in DATE_COLUMNS or field in ('下单时间','下请购单日期'):
                    try:
                        date.fromisoformat(str(value)[:10]);sheet['cells'][address]['date']=True
                    except ValueError:pass
                edit_cell(sheet,address,value)
            sheet['rows']=max(sheet['rows'],r);row['row']=r;count+=1;state='已加入'
        elif state in ('新增','补充空白','待更新关联行'):reason='尚未确认加入、补充或更新计划总表'
        if state in ('已存在','已加入'):
            links=updated.setdefault('order_links',[])
            links[:]=[l for l in links if not (l['order_id']==row['order_id'] and l['item_id']==row['item_id'] and l['sheet']==row['sheet'])]
            links.append(dict(order_id=row['order_id'],item_id=row['item_id'],sheet=row['sheet'],row=row['row']))
            if row['gaps']:reason='资料待补齐：'+'、'.join(row['gaps'])
            else:reason=''
        if reason and reason!='已存在，不重复加入':pending[row['order_id']].append(dict(key=row['key'],sheet=row['sheet'],model=row['model'],reason=reason))
    if count:
        for sheet in updated['sheets']:sheet['formulas_stale']=True
    for order in saved:
        order['plan_targets']=list(targets);order['plan_sync_checked']=True;order['plan_pending']=pending[order['id']]
    return updated,saved,count
