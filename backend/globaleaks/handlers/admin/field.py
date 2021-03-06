# -*- coding: UTF-8
#
#   /admin/fields
#   *****
# Implementation of the code executed on handler /admin/fields
#
import copy

from storm.expr import And, Not, In

from globaleaks import models
from globaleaks.handlers.base import BaseHandler
from globaleaks.handlers.public import serialize_field
from globaleaks.orm import transact
from globaleaks.rest import errors, requests
from globaleaks.utils.structures import fill_localized_keys
from globaleaks.utils.utility import log


def db_import_fields(store, step, fieldgroup, fields):
    for field in fields:
        f_attrs = copy.deepcopy(field['attrs'])
        f_options = copy.deepcopy(field['options'])
        f_children = copy.deepcopy(field['children'])

        del field['attrs'], field['options'], field['children']

        f = models.db_forge_obj(store, models.Field, field)

        for attr in f_attrs:
            f_attrs[attr]['name'] = attr
            f.attrs.add(models.db_forge_obj(store, models.FieldAttr, f_attrs[attr]))

        for option in f_options:
            f.options.add(models.db_forge_obj(store, models.FieldOption, option))

        if step:
            step.children.add(f)
        else:
            fieldgroup.children.add(f)

        if f_children:
            db_import_fields(store, None, f, f_children)


def db_update_fieldoption(store, fieldoption_id, option, language):
    fill_localized_keys(option, models.FieldOption.localized_keys, language)

    if fieldoption_id is not None:
        o = store.find(models.FieldOption, models.FieldOption.id == fieldoption_id).one()
    else:
        o = None

    if o is None:
        o = models.FieldOption()
        store.add(o)

    o.trigger_field = option['trigger_field'] if option['trigger_field'] != '' else None
    o.trigger_step = option['trigger_step'] if option['trigger_step'] != '' else None

    o.update(option)

    return o.id


def db_update_fieldoptions(store, field_id, options, language):
    """
    Update options

    :param store: the store on which perform queries.
    :param field_id: the field_id on wich bind the provided options
    :param language: the language of the option definition dict
    """
    options_ids = []

    for option in options:
        option['field_id'] = field_id
        options_ids.append(db_update_fieldoption(store, option['id'], option, language))

    store.find(models.FieldOption, And(models.FieldOption.field_id == field_id, Not(In(models.FieldOption.id, options_ids)))).remove()


def db_update_fieldattr(store, field_id, attr_name, attr_dict, language):
    attr = store.find(models.FieldAttr, And(models.FieldAttr.field_id == field_id, models.FieldAttr.name == attr_name)).one()
    if not attr:
        attr = models.FieldAttr()

    attr_dict['name'] = attr_name
    attr_dict['field_id'] = field_id

    if attr_dict['type'] == 'bool':
        attr_dict['value'] = 'True' if attr_dict['value'] == True else 'False'
    elif attr_dict['type'] == u'localized':
        fill_localized_keys(attr_dict, ['value'], language)

    attr.update(attr_dict)

    store.add(attr)

    return attr.id


def db_update_fieldattrs(store, field_id, field_attrs, language):
    attrs_ids = [db_update_fieldattr(store, field_id, attr_name, attr, language) for attr_name, attr in field_attrs.iteritems()]

    store.find(models.FieldAttr, And(models.FieldAttr.field_id == field_id, Not(In(models.FieldAttr.id, attrs_ids)))).remove()


def db_create_field(store, field_dict, language):
    """
    Create and add a new field to the store, then return the new serialized object.

    :param store: the store on which perform queries.
    :param field_dict: the field definition dict
    :param language: the language of the field definition dict
    :return: a serialization of the object
    """
    fill_localized_keys(field_dict, models.Field.localized_keys, language)

    field = models.Field(field_dict)

    if field_dict['template_id'] != '':
        field.template_id = field_dict['template_id']

    if field_dict['step_id'] != '':
        field.step_id = field_dict['step_id']

    if field_dict['fieldgroup_id'] != '':
        ancestors = set(fieldtree_ancestors(store, field_dict['fieldgroup_id']))

        if field.id == field_dict['fieldgroup_id'] or field.id in ancestors:
            raise errors.InvalidInputFormat("Provided field association would cause recursion loop")

        field.fieldgroup_id = field_dict['fieldgroup_id']

    store.add(field)

    if field.template:
        # special handling of the whistleblower_identity field
        if field.template.key == 'whistleblower_identity':
            if field.step:
                if store.find(models.Field, models.Field.key == u'whistleblower_identity',
                                            models.Field.step_id == models.Step.id,
                                            models.Step.questionnaire_id == models.Questionnaire.id,
                                            models.Questionnaire.id == field.step.questionnaire_id).count() == 0:
                    field.step.questionnaire.enable_whistleblower_identity = True
                else:
                    raise errors.InvalidInputFormat("Whistleblower identity field already present")
            else:
                raise errors.InvalidInputFormat("Cannot associate whistleblower identity field to a fieldgroup")

    else:
        db_update_fieldattrs(store, field.id, field_dict['attrs'], language)
        db_update_fieldoptions(store, field.id, field_dict['options'], language)

    if field.instance != 'reference':
        for c in field_dict['children']:
            c['fieldgroup_id'] = field.id
            db_create_field(store, c, language)

    return field


@transact
def create_field(store, field_dict, language):
    """
    Transaction that perform db_create_field
    """
    field = db_create_field(store, field_dict, language)

    return serialize_field(store, field, language)


def db_update_field(store, field_id, field_dict, language):
    field = models.Field.get(store, field_id)
    if not field:
        raise errors.FieldIdNotFound

    # To be uncommented upon completion of fields implementaion
    # if not field.editable:
    #     raise errors.FieldNotEditable

    try:
        # make not possible to change field type
        field_dict['type'] = field.type

        if field_dict['instance'] != 'reference':
            fill_localized_keys(field_dict, models.Field.localized_keys, language)

            db_update_fieldattrs(store, field.id, field_dict['attrs'], language)
            db_update_fieldoptions(store, field.id, field_dict['options'], language)

            # full update
            field.update(field_dict)

        else:
            # partial update
            partial_update = {
              'x': field_dict['x'],
              'y': field_dict['y'],
              'width': field_dict['width'],
              'multi_entry': field_dict['multi_entry']
            }

            field.update(partial_update)
    except Exception as dberror:
        log.err('Unable to update field: {e}'.format(e=dberror))
        raise errors.InvalidInputFormat(dberror)

    return field


@transact
def update_field(store, field_id, field, language):
    """
    Update the specified field with the details.
    raises :class:`globaleaks.errors.FieldIdNotFound` if the field does
    not exist.

    :param store: the store on which perform queries.
    :param field_id: the field_id of the field to update
    :param field: the field definition dict
    :param language: the language of the field definition dict
    :return: a serialization of the object
    """
    field = db_update_field(store, field_id, field, language)

    return serialize_field(store, field, language)


@transact
def delete_field(store, field_id):
    """
    Delete the field object corresponding to field_id

    If the field has children, remove them as well.
    If the field is immediately attached to a step object, remove it as well.

    :param store: the store on which perform queries.
    :param field_id: the id corresponding to the field.
    :raises FieldIdNotFound: if no such field is found.
    """
    field = store.find(models.Field, models.Field.id == field_id).one()
    if not field:
        raise errors.FieldIdNotFound

    # TODO: to be uncommented upon completion of fields implementaion
    # if not field.editable:
    #     raise errors.FieldNotEditable

    if field.instance == 'template':
        if store.find(models.Field, models.Field.template_id == field.id).count():
            raise errors.InvalidInputFormat("Cannot remove the field template as it is used by one or more questionnaires")


    if field.template:
        # special handling of the whistleblower_identity field
        if field.template.key == 'whistleblower_identity':
            if field.step is not None:
                field.step.questionnaire.enable_whistleblower_identity = False

    store.remove(field)


def fieldtree_ancestors(store, field_id):
    """
    Given a field_id, recursively extract its parents.

    :param store: the store on which perform queries.
    :param field_id: the parent id.
    :return: a generator of Field.id
    """
    field = store.find(models.Field, models.Field.id == field_id).one()
    if field.fieldgroup_id is not None:
        yield field.fieldgroup_id
        yield fieldtree_ancestors(store, field.fieldgroup_id)


@transact
def get_fieldtemplate_list(store, language):
    """
    Serialize all the field templates localizing their content depending on the language.

    :param store: the store on which perform queries.
    :param language: the language of the field definition dict
    :return: the current field list serialized.
    :rtype: list of dict
    """
    ret = []
    for f in store.find(models.Field, And(models.Field.instance == u'template',
                                          models.Field.fieldgroup_id == None)):
        ret.append(serialize_field(store, f, language))

    return ret


class FieldTemplatesCollection(BaseHandler):
    check_roles = 'admin'

    def get(self):
        """
        Return a list of all the fields templates available.

        :return: the list of field templates registered on the node.
        :rtype: list
        """
        return get_fieldtemplate_list(self.request.language)

    def post(self):
        """
        Create a new field template.
        """
        validator = requests.AdminFieldDesc if self.request.language is not None else requests.AdminFieldDescRaw

        request = self.validate_message(self.request.content.read(), validator)

        return create_field(request, self.request.language)


class FieldTemplateInstance(BaseHandler):
    check_roles = 'admin'
    invalidate_cache = True

    def put(self, field_id):
        """
        Update a single field template's attributes.

        :param field_id:
        :rtype: FieldTemplateDesc
        :raises FieldIdNotFound: if there is no field with such id.
        :raises InvalidInputFormat: if validation fails.
        """
        request = self.validate_message(self.request.content.read(),
                                        requests.AdminFieldDesc)

        return update_field(field_id,
                            request,
                            self.request.language)

    def delete(self, field_id):
        """
        Delete a single field template.

        :param field_id:
        :raises FieldIdNotFound: if there is no field with such id.
        """
        return delete_field(field_id)


class FieldCollection(BaseHandler):
    """
    Operation to create a field

    /admin/fields
    """
    check_roles = 'admin'
    cache_resource = True
    invalidate_cache = True

    def post(self):
        """
        Create a new field.

        :return: the serialized field
        :rtype: AdminFieldDesc
        :raises InvalidInputFormat: if validation fails.
        """
        request = self.validate_message(self.request.content.read(),
                                        requests.AdminFieldDesc)

        return create_field(request,
                            self.request.language)


class FieldInstance(BaseHandler):
    """
    Operation to iterate over a specific requested Field

    /admin/fields
    """
    check_roles = 'admin'
    invalidate_cache = True

    def put(self, field_id):
        """
        Update attributes of the specified step.

        :param field_id:
        :return: the serialized field
        :rtype: AdminFieldDesc
        :raises FieldIdNotFound: if there is no field with such id.
        :raises InvalidInputFormat: if validation fails.
        """
        request = self.validate_message(self.request.content.read(),
                                        requests.AdminFieldDesc)

        return update_field(field_id,
                            request,
                            self.request.language)

    def delete(self, field_id):
        """
        Delete a single field.

        :param field_id:
        :raises FieldIdNotFound: if there is no field with such id.
        :raises InvalidInputFormat: if validation fails.
        """
        return delete_field(field_id)
