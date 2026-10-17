"""Optional read-only Gradio viewer. Scientific jobs belong to MCP / CLI / REST."""

import html
from pathlib import Path

import gradio as gr
import plotly.graph_objects as go

from opensubsurface.adapters.seismic import open_volume, read_section
from opensubsurface.demo_norne import open_demo
from opensubsurface.errors import DomainError
from opensubsurface.viewer_links import artifact_path

CSS = """.gradio-container{max-width:1480px!important;font-family:system-ui!important}
footer{display:none!important}#brand h1{color:var(--body-text-color);letter-spacing:-1px}#brand{border-bottom:1px solid #dbe5ec}
"""


def empty_plot(title="Select a seismic artifact"):
    fig = go.Figure()
    fig.update_layout(template="plotly_white", title=title, height=550)
    return fig


def create_ui(service):
    def refresh(pid):
        projects = service.store.list_projects()
        choices = [(p["name"] + " · " + p["id"][-6:], p["id"]) for p in projects]
        if pid not in {p["id"] for p in projects}:
            pid = projects[-1]["id"] if projects else None
        objects = service.store.list_objects(pid, limit=200) if pid else []
        options = [
            (f"{o['kind']} · {o['id']} · r{o['revision']}", f"{o['id']}:{o['revision']}") for o in objects
        ]
        selected = next(
            (f"{o['id']}:{o['revision']}" for o in reversed(objects) if o["kind"] == "scene"),
            options[0][1] if options else None,
        )
        rows = [[o["kind"], o["id"], o["revision"], o["content_hash"][:16]] for o in objects]
        summary = (
            f"**{len(objects)} revisions on this page.** [All revisions](/viewer/projects/{pid})"
            if pid
            else "Create a project through MCP / CLI / REST, or open the Norne demo."
        )
        return (
            gr.update(choices=choices, value=pid),
            rows,
            gr.update(choices=options, value=selected),
            summary,
        )

    def preview(pid, selected):
        if not pid or not selected:
            return "<p>Select a project and revision.</p>", {}
        oid, revision = selected.rsplit(":", 1)
        obj = service.store.object(pid, dict(id=oid, revision=int(revision)))
        path = artifact_path(pid, obj)
        frame = (
            f'<p><a href="{path}" target="_blank" rel="noopener">Open result page</a></p>'
            f'<iframe title="Result preview" src="{path}" style="width:100%;height:740px;border:0"></iframe>'
        )
        return frame, obj

    def norne():
        try:
            result = open_demo(service.store)
            return (*refresh(result["project_id"]), result)
        except DomainError as error:
            raise gr.Error(
                error.message
                if not any("\u0400" <= c <= "\u04ff" for c in error.message)
                else f"{error.code}. Check your selection and server logs."
            )

    def upload(pid, filename):
        if not pid or not filename:
            raise gr.Error("Select a project and file")
        try:
            with Path(filename).open("rb") as stream:
                return service.store.upload(pid, Path(filename).name, stream)
        except DomainError as error:
            raise gr.Error(
                error.message
                if not any("\u0400" <= c <= "\u04ff" for c in error.message)
                else f"{error.code}. Check your selection and server logs."
            )

    def add_folder():
        from opensubsurface.adapters.folder_dialog import add_folder as register_folder

        try:
            return register_folder(service.store)
        except DomainError as error:
            raise gr.Error(
                error.message
                if not any("\u0400" <= c <= "\u04ff" for c in error.message)
                else f"{error.code}. Check your selection and server logs."
            )

    def seismic_plot(pid, selected, axis, index):
        if not pid or not selected:
            return empty_plot()
        oid, revision = selected.rsplit(":", 1)
        obj = service.store.object(pid, dict(id=oid, revision=int(revision)))
        if obj["kind"] != "seismic":
            return empty_plot()
        store, group = open_volume(service.store.path(obj, "cube.zip"))
        try:
            dimension = {"Inline": 0, "Crossline": 1, "Sample": 2}[axis]
            section = read_section(group, dimension, int(index))
            if dimension < 2:
                x = group["crossline" if dimension == 0 else "inline"][:]
                y = group["sample"][:]
            else:
                x, y = group["inline"][:], group["crossline"][:]
            fig = go.Figure(go.Heatmap(z=section.T, x=x, y=y, colorscale="RdBu", zmid=0))
            if dimension < 2:
                fig.update_yaxes(
                    autorange="reversed",
                    title="TWT (s)" if obj["summary"]["domain"] == "twt" else "Depth (m)",
                )
            fig.update_layout(template="plotly_white", height=550, title=html.escape(f"{axis} {int(index)}"))
            return fig
        except DomainError as error:
            raise gr.Error(
                error.message
                if not any("\u0400" <= c <= "\u04ff" for c in error.message)
                else f"{error.code}. Check your selection and server logs."
            )
        finally:
            store.close()

    with gr.Blocks(title="Kanysh Basic · Local Viewer", css=CSS) as app:
        gr.Markdown("# Kanysh Basic\nMCP server for subsurface modeling + local web viewer", elem_id="brand")
        gr.Markdown(
            "Run calculations in your connected MCP client, through CLI or REST. View data, revisions and results here."
        )
        with gr.Row():
            with gr.Column(scale=1, min_width=280):
                project = gr.Dropdown(choices=[], label="Project")
                folder_button = gr.Button("Add folder")
                folder_info = gr.JSON(label="Local source (owner only)")
                refresh_button = gr.Button("Refresh")
                norne_button = gr.Button("Open Norne demo", variant="primary")
                gr.Markdown("The demo opens saved public artifacts. It does not calculate or download data.")
                with gr.Accordion("Demo provenance", open=False):
                    demo_info = gr.JSON(label="Norne / OPM")
            with gr.Column(scale=4):
                summary = gr.Markdown()
                with gr.Accordion("Revision history", open=False):
                    revisions = gr.Dataframe(
                        headers=["Type", "ID", "Revision", "SHA-256"],
                        interactive=False,
                        label="Projects and revisions",
                    )
                artifact = gr.Dropdown(choices=[], label="Artifact and revision")
                with gr.Tab("Reports and 3D scene"):
                    view = gr.HTML()
                with gr.Tab("Seismic sections"):
                    with gr.Row():
                        axis = gr.Dropdown(["Inline", "Crossline", "Sample"], value="Inline", label="Section")
                        index = gr.Number(value=0, minimum=0, precision=0, label="Index")
                    slice_button = gr.Button("Show section")
                    seismic_view = gr.Plot(value=empty_plot())
                with gr.Tab("Files"):
                    gr.Markdown(
                        "Files are saved in the project. Use your MCP client to import and calculate. For large models, choose Add folder."
                    )
                    file = gr.File(type="filepath", label="Upload file", file_count="single")
                    upload_button = gr.Button("Save file to project")
                    upload_info = gr.JSON(label="Saved file")
                with gr.Accordion("Metadata and provenance", open=False):
                    metadata = gr.JSON()

        folder_button.click(add_folder, outputs=folder_info, api_name=False, concurrency_limit=1)
        outputs = [project, revisions, artifact, summary]
        app.load(refresh, inputs=project, outputs=outputs).then(
            preview, inputs=[project, artifact], outputs=[view, metadata]
        )
        refresh_button.click(refresh, inputs=project, outputs=outputs).then(
            preview, inputs=[project, artifact], outputs=[view, metadata]
        )
        project.input(refresh, inputs=project, outputs=outputs).then(
            preview, inputs=[project, artifact], outputs=[view, metadata]
        )
        artifact.change(preview, inputs=[project, artifact], outputs=[view, metadata])
        norne_button.click(norne, outputs=[*outputs, demo_info]).then(
            preview, inputs=[project, artifact], outputs=[view, metadata]
        )
        slice_button.click(seismic_plot, inputs=[project, artifact, axis, index], outputs=seismic_view)
        upload_button.click(upload, inputs=[project, file], outputs=upload_info)
    return app
