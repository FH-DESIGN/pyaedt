from __future__ import absolute_import

from collections import OrderedDict
import os
import re

from pyaedt import pyaedt_function_handler
from pyaedt.generic.general_methods import _uname
from pyaedt.generic.general_methods import read_csv


class ComponentArray(object):
    """Manages object attributes for 3DComponent array.

    Parameters
    ----------
    app : :class:`pyaedt.Hfss`
        Hfss pyaedt object.
    name : str, optional
        Array name. The default value is ``None``.
    props : dict, optional
        Dictionary of properties. The default value is ``None``.

    Examples
    --------
    Basic usage demonstrated with an HFSS design with an existing array:

    >>> from pyaedt import Hfss
    >>> aedtapp = Hfss(projectname="Array.aedt")
    >>> array_names = aedtapp.component_array_names[0]
    >>> array = aedtapp.component_array[array_names[0]]
    """

    def __init__(self, app, name=None, props=None):
        # Public attributes
        self.logger = app.logger
        self.update_cells = True

        # Private attributes
        self.__app = app
        if name is None:
            name = _uname("Array_")
        self.__name = name
        # Data that can not be obtained from CSV
        try:
            self.__cs_id = props["ArrayDefinition"]["ArrayObject"]["ReferenceCSID"]
        except AttributeError:  # pragma: no cover
            self.__cs_id = 1

        self.__omodel = self.__app.get_oo_object(self.__app.odesign, "Model")
        self.__oarray = self.__app.get_oo_object(self.__omodel, name)
        self.__array_info_path = None
        self.__cells = None
        self.__post_processing_cells = {}

        # Leverage csv file if possible (aedt version > 2023.2)
        if self.__app.settings.aedt_version > "2023.2":  # pragma: no cover
            self.export_array_info(array_path=None)
            self.__array_info_path = os.path.join(self.__app.toolkit_directory, "array_info.csv")

    @property
    def name(self):
        """Name of the array.

        Returns
        -------
        str
           Name of the array.
        """
        return self.__name

    @name.setter
    def name(self, array_name):
        if array_name not in self.__app.component_array_names:
            if array_name != self.__name:
                self.__oarray.SetPropValue("Name", array_name)
                self.__app.component_array.update({array_name: self})
                self.__app.component_array_names = list(self.__app.omodelsetup.GetArrayNames())
                del self.__app.component_array[self.__name]
                self.__name = array_name
        else:  # pragma: no cover
            self.logger.warning("Name %s already assigned in the design", array_name)

    @property
    def properties(self):
        """Retrieve the properties of the component array.

        Returns
        -------
        dict
           An ordered dictionary of the properties of the component array.
        """
        # From 2024R1, array information can be loaded from a CSV
        if self.__array_info_path and os.path.exists(self.__array_info_path):  # pragma: no cover
            res = self.parse_array_info_from_csv(self.__array_info_path)
        else:
            self.__app.save_project()
            res = self.__get_properties_from_aedt()
        return res

    @property
    def component_names(self):
        """List of component names.

        Returns
        -------
        list
        """
        return self.properties["component"]

    @property
    def cells(self):
        """List of cell objects.

        Returns
        -------
        list
            List of :class:`pyaedt.modeler.cad.component_array.CellArray`
        """

        if not self.update_cells:
            return self.__cells

        if self.__app.settings.aedt_version > "2023.2":  # pragma: no cover
            self.export_array_info(array_path=None)
            self.__array_info_path = os.path.join(self.__app.toolkit_directory, "array_info.csv")

        self.__cells = [[None for _ in range(self.b_size)] for _ in range(self.a_size)]
        array_props = self.properties
        component_names = self.component_names
        for row_cell in range(0, self.a_size):
            for col_cell in range(0, self.b_size):
                self.__cells[row_cell][col_cell] = CellArray(row_cell, col_cell, array_props, component_names, self)
        return self.__cells

    @property
    def post_processing_cells(self):
        """Postprocessing cells.

        Returns
        -------
        dict
           Postprocessing cells of each component.
        """
        if not self.__post_processing_cells:
            self.__post_processing_cells = {}
            component_info = {}
            for row, row_info in enumerate(self.cells, start=1):
                for col, col_info in enumerate(row_info, start=1):
                    name = col_info.component
                    component_info.setdefault(name, []).append([row, col])

            for component_name, component_cells in component_info.items():
                if component_name not in self.__post_processing_cells.keys() and component_name is not None:
                    self.__post_processing_cells[component_name] = component_cells[0]

        return self.__post_processing_cells

    @post_processing_cells.setter
    def post_processing_cells(self, val):
        if isinstance(val, dict):
            self.__post_processing_cells = val
            self.edit_array()

        else:  # pragma: no cover
            self.logger.error("Dictionary with component names and cell not correct")

    @property
    def visible(self):
        """Array visibility.

        Returns
        -------
        bool
           Array visibility.
        """
        return self.__app.get_oo_property_value(self.__omodel, self.name, "Visible")

    @visible.setter
    def visible(self, val):
        self.__oarray.SetPropValue("Visible", val)

    @property
    def show_cell_number(self):
        """Show array cell number.

        Returns
        -------
        bool
           Cell number visibility.
        """
        return self.__app.get_oo_property_value(self.__omodel, self.name, "Show Cell Number")

    @show_cell_number.setter
    def show_cell_number(self, val):
        self.__oarray.SetPropValue("Show Cell Number", val)

    @property
    def render_choices(self):
        """Render name choices.

        Returns
        -------
        list
           Render names.
        """
        return list(self.__oarray.GetPropValue("Render/Choices"))

    @property
    def render(self):
        """Array rendering.

        Returns
        -------
        str
           Rendering type.
        """
        return self.__app.get_oo_property_value(self.__omodel, self.name, "Render")

    @render.setter
    def render(self, val):
        if val not in self.render_choices:
            self.logger.warning("Render value not available")
        else:
            self.__oarray.SetPropValue("Render", val)

    @property
    def render_id(self):
        """Array rendering index.

        Returns
        -------
        int
           Rendering ID.
        """
        res = self.render_choices.index(self.render)
        return res

    @property
    def a_vector_choices(self):
        """A vector name choices.

        Returns
        -------
        list
           Lattice vector names.
        """
        return list(self.__app.get_oo_property_value(self.__omodel, self.name, "A Vector/Choices"))

    @property
    def b_vector_choices(self):
        """B vector name choices.

        Returns
        -------
        list
           Lattice vector names.
        """
        return list(self.__app.get_oo_property_value(self.__omodel, self.name, "B Vector/Choices"))

    @property
    def a_vector_name(self):
        """A vector name.

        Returns
        -------
        str
           Lattice vector name.
        """
        return self.__app.get_oo_property_value(self.__omodel, self.name, "A Vector")

    @a_vector_name.setter
    def a_vector_name(self, val):
        if val in self.a_vector_choices:
            self.__oarray.SetPropValue("A Vector", val)
        else:
            self.logger.warning("A vector name not available")

    @property
    def b_vector_name(self):
        """B vector name.

        Returns
        -------
        str
           Lattice vector name.
        """
        return self.__oarray.GetPropValue("B Vector")

    @b_vector_name.setter
    def b_vector_name(self, val):
        if val in self.b_vector_choices:
            self.__oarray.SetPropValue("B Vector", val)
        else:
            self.logger.warning("B vector name not available")

    @property
    def a_size(self):
        """A cell count.

        Returns
        -------
        int
           Number of cells in A direction.
        """
        return int(self.__app.get_oo_property_value(self.__omodel, self.name, "A Cell Count"))

    @a_size.setter
    def a_size(self, val):  # pragma: no cover
        # Bug in 2024.1, not possible to change cell count.
        # self.__oarray.SetPropValue("A Cell Count", val)
        self.logger.error("AEDT (2024.1) does not yet allow to change the cell count.")

    @property
    def b_size(self):
        """B cell count.

        Returns
        -------
        int
           Number of cells in B direction.
        """
        return int(self.__app.get_oo_property_value(self.__omodel, self.name, "B Cell Count"))

    @b_size.setter
    def b_size(self, val):  # pragma: no cover
        # Bug in 2024.1, not possible to change cell count.
        # self.__oarray.SetPropValue("B Cell Count", val)
        self.logger.error("AEDT (2024.1) does not yet allow to change the cell count.")

    @property
    def padding_cells(self):
        """Number of padding cells.

        Returns
        -------
        int
           Number of padding cells.
        """
        return int(self.__app.get_oo_property_value(self.__omodel, self.name, "Padding"))

    @padding_cells.setter
    def padding_cells(self, val):
        self.__oarray.SetPropValue("Padding", val)

    @property
    def coordinate_system(self):
        """Coordinate system.

        Returns
        -------
        str
           Coordinate system name.
        """
        cs_dict = self.__map_coordinate_system_to_id()
        res = "Global"
        for name, id in cs_dict.items():
            if id == self.__cs_id:
                res = name
        if res == "Global":
            self.logger.warning("Coordinate system is not loaded, please save the project.")
        return res

    @coordinate_system.setter
    def coordinate_system(self, name):
        cs_dict = self.__map_coordinate_system_to_id()
        if name not in cs_dict.keys():
            self.logger.warning("Coordinate system is not loaded, please save the project.")
        else:
            self.__cs_id = cs_dict[name]
            self.edit_array()

    @property
    def lattice_vector(self):
        """Get model lattice vector.

        Returns
        -------
        list

        References
        ----------
        >>> oModule.GetLatticeVectors()

        """
        return self.__app.omodelsetup.GetLatticeVectors()

    @pyaedt_function_handler()
    def delete(self):
        """Delete the array.

        References
        ----------

        >>> oModule.DeleteArray
        """
        self.__app.omodelsetup.DeleteArray()
        del self.__app.component_array[self.name]
        self.__app.component_array_names = list(self.__app.get_oo_name(self.__app.odesign, "Model"))

    @pyaedt_function_handler()
    def export_array_info(self, array_path=None):
        """Export array information to CSV file.

        References
        ----------

        >>> oModule.ExportArray
        """
        if self.__app.settings.aedt_version < "2024.1":  # pragma: no cover
            self.logger.warning("This feature is not available in " + str(self.__app.settings.aedt_version))
            return False

        if not array_path:  # pragma: no cover
            array_path = os.path.join(self.__app.toolkit_directory, "array_info.csv")
        self.__app.omodelsetup.ExportArray(self.name, array_path)
        return True

    @pyaedt_function_handler()
    def parse_array_info_from_csv(self, csv_file):  # pragma: no cover
        """Parse array CSV file.

        Returns
        -------
        dict
           An ordered dictionary of the properties of the component array.
        """

        info = read_csv(csv_file)
        if not info:
            self.logger.error("Data from CSV not loaded.")
            return False

        components = []
        array_matrix = []
        array_matrix_rotation = []
        array_matrix_active = []

        # Components
        start_str = ["Component Index", "Component Name"]
        end_str = ["Source Row", "Source Column", "Source Name", "Magnitude", "Phase"]
        capture_data = False
        line_cont = 0
        for element_data in info:
            if element_data == start_str:
                capture_data = True
            elif element_data == end_str:
                break
            elif capture_data:
                components.append(element_data[1])
            line_cont += 1

        # Array matrix
        start_str = ["Array", "Format: Component_index:Rotation_angle:Active_or_Passive"]
        capture_data = False
        for element_data in info[line_cont + 1 :]:
            if capture_data:
                rows = element_data[:-1]
                component_index = []
                rotation = []
                active_passive = []

                for row in rows:
                    split_elements = row.split(":")

                    # Check for non-empty strings
                    if split_elements[0]:
                        component_index.append(int(split_elements[0]))
                    else:
                        component_index.append(-1)

                    # Some elements might not have the rotation and active/passive status, so we check for their
                    # existence
                    if split_elements[0] and len(split_elements) > 1:
                        string_part = re.findall("[a-zA-Z]+", split_elements[1])
                        if string_part and string_part[0] == "deg":
                            rot = re.findall(r"[+-]?\d+\.\d+", split_elements[1])
                            rotation.append(int(float(rot[0])))
                            if len(split_elements) > 2:
                                active_passive.append(bool(int(split_elements[2])))
                            else:
                                active_passive.append(True)
                        else:
                            active_passive.append(False)
                            rotation.append(0)
                    elif split_elements[0]:
                        active_passive.append(True)
                        rotation.append(0)
                    else:
                        active_passive.append(False)
                        rotation.append(0)

                array_matrix.append(component_index)
                array_matrix_rotation.append(rotation)
                array_matrix_active.append(active_passive)
            elif element_data == start_str:
                capture_data = True

        res = OrderedDict()
        res["component"] = components
        res["active"] = array_matrix_active
        res["rotation"] = array_matrix_rotation
        res["cells"] = array_matrix
        return res

    @pyaedt_function_handler()
    def edit_array(self):
        """Edit array.

        Returns
        -------
        bool
            ``True`` when successful, ``False`` when failed

        References
        ----------

        >>> oModule.EditArray
        """

        args = [
            "NAME:" + self.name,
            "Name:=",
            self.name,
            "UseAirObjects:=",
            True,
            "RowPrimaryBnd:=",
            self.a_vector_name,
            "ColumnPrimaryBnd:=",
            self.b_vector_name,
            "RowDimension:=",
            self.a_size,
            "ColumnDimension:=",
            self.b_size,
            "Visible:=",
            self.visible,
            "ShowCellNumber:=",
            self.show_cell_number,
            "RenderType:=",
            self.render_id,
            "Padding:=",
            self.padding_cells,
            "ReferenceCSID:=",
            self.__cs_id,
        ]

        cells = ["NAME:Cells"]
        component_info = {}
        for row, row_info in enumerate(self.cells, start=1):
            for col, col_info in enumerate(row_info, start=1):
                name = col_info.component
                component_info.setdefault(name, []).append([row, col])

        for component_name, component_cells in component_info.items():
            if component_name:
                cells.append(component_name + ":=")
                component_cells_str = ", ".join(str(item) for item in component_cells)
                cells.append([component_cells_str])

        rotations = ["NAME:Rotation"]
        component_rotation = {}
        for row, row_info in enumerate(self.cells, start=1):
            for col, col_info in enumerate(row_info, start=1):
                component_rotation.setdefault(col_info.rotation, []).append([row, col])

        for rotation, rotation_cells in component_rotation.items():
            rotations.append(str(rotation) + " deg:=")
            component_cells_str = ", ".join(str(item) for item in rotation_cells)
            #
            rotations.append([component_cells_str])

        args.append(cells)
        args.append(rotations)
        args.append("Active:=")

        component_active = []
        for row, row_info in enumerate(self.cells, start=1):
            for col, col_info in enumerate(row_info, start=1):
                if col_info.is_active:
                    component_active.append([row, col])
        if component_active:
            args.append(", ".join(str(item) for item in component_active))
        else:
            args.append("All")

        post = ["NAME:PostProcessingCells"]
        for component_name, values in self.post_processing_cells.items():
            post.append(component_name + ":=")
            post.append([str(values[0]), str(values[1])])
        args.append(post)

        args.append("Colors:=")
        col = []
        args.append(col)
        self.__app.omodelsetup.EditArray(args)

        return True

    @pyaedt_function_handler()
    def get_cell(self, row, col):
        """Get cell object corresponding to a row and column.

        Returns
        -------
        :class:`pyaedt.modeler.cad.component_array.CellArray`

        """
        if row > self.a_size or col > self.b_size:
            self.logger.error("Specified cell does not exist.")
            return False
        if row <= 0 or col <= 0:
            self.logger.error("Row and column index start with ``1``.")
            return False
        return self.cells[row - 1][col - 1]

    @pyaedt_function_handler()
    def __get_properties_from_aedt(self):
        """Get array properties from AEDT file.

        Returns
        -------
        dict

        """
        props = self.__app.design_properties
        component_id = {}
        user_defined_models = props["ModelSetup"]["GeometryCore"]["GeometryOperations"]["UserDefinedModels"][
            "UserDefinedModel"
        ]
        if not isinstance(user_defined_models, list):
            user_defined_models = [user_defined_models]
        for component_defined in user_defined_models:
            component_id[component_defined["ID"]] = component_defined["Attributes"]["Name"]

        components_map = props["ArrayDefinition"]["ArrayObject"]["ComponentMap"]
        components = [None] * len(components_map)
        for comp in props["ArrayDefinition"]["ArrayObject"]["ComponentMap"]:
            key, value = comp.split("=")
            key = int(key.strip("'"))
            value = int(value)
            components[key - 1] = component_id[value]

        res = OrderedDict()
        res["component"] = components
        res["active"] = props["ArrayDefinition"]["ArrayObject"]["Active"]["matrix"]
        res["rotation"] = props["ArrayDefinition"]["ArrayObject"]["Rotation"]["matrix"]
        res["cells"] = props["ArrayDefinition"]["ArrayObject"]["Cells"]["matrix"]
        return res

    @pyaedt_function_handler()
    def __map_coordinate_system_to_id(self):
        """Map coordinate system to ID.

        Returns
        -------
        Dict[str, int]
        """
        res = {"Global": 1}
        if self.__app.design_properties and "ModelSetup" in self.__app.design_properties:  # pragma: no cover
            cs = self.__app.design_properties["ModelSetup"]["GeometryCore"]["GeometryOperations"]["CoordinateSystems"]
            for key, val in cs.items():
                try:
                    if isinstance(val, dict):
                        val = [val]
                    for ite in val:
                        name = ite["Attributes"]["Name"]
                        cs_id = ite["ID"]
                        res[name] = cs_id
                except AttributeError:
                    pass
        return res


class CellArray(object):
    """Manages object attributes for 3DComponent and User Defined Model.

    Parameters
    ----------
    row : int
        The row index of the cell.
    col : int
        The column index of the cell.
    array_props : dict
        Dictionary containing the properties of the array.
    component_names : list
        List of component names in the array.
    array_obj : class:`pyaedt.modeler.cad.component_array.ComponentArray`
        The instance of the array containing the cell.

    """

    def __init__(self, row, col, array_props, component_names, array_obj):
        self.__row = row + 1
        self.__col = col + 1
        self.__array_obj = array_obj
        self.__cell_props = OrderedDict(
            {
                "component": array_props["cells"][row][col],
                "active": array_props["active"][row][col],
                "rotation": array_props["rotation"][row][col],
            }
        )
        self.__rotation = self.__cell_props["rotation"]
        self.__is_active = self.__cell_props["active"]

        component_index = self.__cell_props["component"]
        if component_index == -1:
            self.__component = None
        else:
            self.__component = component_names[component_index - 1]

    @property
    def rotation(self):
        """Gets the rotation value of the cell object.

        Returns
        -------
        int
        """
        return self.__rotation

    @rotation.setter
    def rotation(self, val):
        if val in [0, 90, 180, 270]:
            self.__rotation = val
            self.__array_obj.update_cells = False
            self.__array_obj.edit_array()
            self.__array_obj.update_cells = True
        else:
            self.__array_obj._logger.error("Rotation must be an integer. 0, 90, 180 and 270 degrees are available.")

    @property
    def component(self):
        """Gets the component name of the cell object.

        Returns
        -------
        str
        """
        return self.__component

    @component.setter
    def component(self, val):
        self.__array_obj.update_cells = False
        if val in self.__array_obj.component_names or val is None:
            if val is None:
                for _, values in self.__array_obj.post_processing_cells.keys():
                    if (values[0], values[1]) == (self.__row, self.__col):
                        flat_cell_list = [item for sublist in self.__array_obj.cells for item in sublist]
                        for cell in flat_cell_list:
                            if cell.component == self.component and cell.col != self.__col or cell.row != self.__row:
                                self.__array_obj.post_processing_cells[self.component] = [cell.row, cell.col]
                                break
                        break
            self.__component = val
            self.__array_obj.edit_array()
            self.__array_obj.update_cells = True
        else:  # pragma: no cover
            self.__array_obj._logger.error("Component must be defined.")

    @property
    def is_active(self):
        """Gets if the cell object is active or passive.

        Returns
        -------
        bool
        """
        return self.__is_active

    @is_active.setter
    def is_active(self, val):
        if isinstance(val, bool):
            self.__is_active = val
            self.__array_obj.update_cells = False
            self.__array_obj.edit_array()
            self.__array_obj.update_cells = True
        else:
            self.__array_obj._logger.error("Only bool type allowed.")